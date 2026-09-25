#include "FlightSimRenderCommandlet.h"

#include "FlightSimCameraDirector.h"
#include "FlightSimOrographic.h"
#include "FlightSimVisualScene.h"
#include "FlightSimScenarioWorld.h"
#include "FlightSimTelemetryRecorder.h"
#include "FlightSimSurfaceAnimator.h"
#include "JSBSimMovementComponent.h"

#include "CineCameraComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/MeshComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/SkyLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "EngineUtils.h"
#include "Dom/JsonObject.h"
#include "Engine/DirectionalLight.h"
#include "Engine/Engine.h"
#include "Engine/SkyLight.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Engine/World.h"
#include "ImageUtils.h"
#include "IImageWrapper.h"
#include "IImageWrapperModule.h"
#include "Modules/ModuleManager.h"
#include "HAL/IConsoleManager.h"
#include "GeoReferencingSystem.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "AssetCompilingManager.h"
#include "RenderingThread.h"
#include "RHI.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "ShaderCompiler.h"
#include "TextureResource.h"

#include <limits>

DEFINE_LOG_CATEGORY(LogFlightSimRender);

namespace
{
	// The engine's unit cube is 100 cm across, so a scale of N gives an N-metre
	// box and every size below reads directly in metres.
	constexpr double RenderCmPerMetre = 100.0;   // unity-unique name
	constexpr double RenderRadiansToDegrees = 57.29577951308232;   // unity-unique name

	// A placeholder airframe: boxes, roughly 747-shaped, with real hinges.
	//
	// This is NOT visual realism -- that is Phase 6 and there is no aircraft
	// asset in this project. It exists to answer one question that a number in
	// a telemetry file cannot: does a JSBSim surface position actually move
	// something a viewer would see? A box that rotates when the FDM says the
	// aileron moved answers it; a photoreal mesh that does not, does not.
	struct FPlaceholderAirframe
	{
		USceneComponent* ElevatorHinge = nullptr;
		USceneComponent* LeftAileronHinge = nullptr;
		USceneComponent* RightAileronHinge = nullptr;
		USceneComponent* RudderHinge = nullptr;
	};

	UStaticMeshComponent* AddBox(AActor* Owner, USceneComponent* Parent,
	                             const TCHAR* Name, UStaticMesh* Cube,
	                             const FVector& CentreMetres, const FVector& SizeMetres)
	{
		UStaticMeshComponent* Box = NewObject<UStaticMeshComponent>(Owner, Name);
		Box->SetupAttachment(Parent);
		Box->SetMobility(EComponentMobility::Movable);
		Box->SetStaticMesh(Cube);
		Box->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Box->RegisterComponent();
		Box->SetRelativeLocation(CentreMetres * RenderCmPerMetre);
		Box->SetRelativeScale3D(SizeMetres);
		return Box;
	}

	// A hinge is a bare scene component at the hinge line, with the surface
	// mesh offset aft of it. Rotating the mesh about its own centre would
	// swing the leading edge forward as well, which is not what a hinge does
	// and would read as a mistake on screen.
	USceneComponent* AddHingedSurface(AActor* Owner, USceneComponent* Parent,
	                                  const TCHAR* HingeName, const TCHAR* MeshName,
	                                  UStaticMesh* Cube, const FVector& HingeMetres,
	                                  const FVector& SizeMetres, const FVector& OffsetMetres)
	{
		USceneComponent* Hinge = NewObject<USceneComponent>(Owner, HingeName);
		Hinge->SetupAttachment(Parent);
		Hinge->SetMobility(EComponentMobility::Movable);
		Hinge->RegisterComponent();
		Hinge->SetRelativeLocation(HingeMetres * RenderCmPerMetre);
		AddBox(Owner, Hinge, MeshName, Cube, OffsetMetres, SizeMetres);
		return Hinge;
	}

	// World -> pixel through the capture's own transform and FOV, so the
	// harness can sample known landmarks instead of guessing regions by eye.
	// -- Phase 10 labels: constants and the 16-bit PNG writer -----------------
	// Names are per-file-unique (gotcha 3: unity builds merge anonymous
	// namespaces). Depth beyond RenderLabelDepthSkyCm is "no geometry" --
	// the sky. The 16-bit depth PNG stores metres / RenderLabelDepthScaleM,
	// saturating at RenderLabelDepthSaturationM; both numbers ride in
	// render.json so no reader has to know them. (Phase 2 retired the 5 cm
	// depth-agreement mask; the ID image comes from the stencil pass below
	// and the instance/class ids here are the DEFAULT pair a card without
	// objects[] gets.)
	constexpr float RenderLabelDepthSkyCm = 5.0e6f;          // 50 km
	constexpr double RenderLabelDepthScaleM = 0.1;
	constexpr double RenderLabelDepthSaturationM = 6553.5;
	constexpr uint8 RenderLabelAircraftInstanceId = 1;
	constexpr uint8 RenderLabelClassAircraft = 1;
	constexpr uint8 RenderLabelClassTerrain = 2;
	// Phase 2 (packages B + C): the post-process material that emits the
	// Custom Depth Stencil as a flat float for the ID pass. Built by
	// scripts/ue_create_materials.py (MD_PostProcess, blendable location
	// "Replacing the Tonemapper", EmissiveColor = SceneTexture:CustomStencil).
	// Absent -> -labels refuses by name; nothing else is written as an ID.
	constexpr const TCHAR* RenderLabelStencilMaterialPath =
		TEXT("/Game/FlightSim/M_CustomStencilID.M_CustomStencilID");
	// The raw depth file is little-endian float32; every UE target is.
	static_assert(PLATFORM_LITTLE_ENDIAN, "frame_NNNN_depth.f32 is declared little-endian");

	// One labelled object as the -labels pass sees it: the card's ids, the
	// actor whose mesh components carry the stencil (null for a scene
	// object like the terrain, whose id goes on every other mesh), and the
	// alone-pass capture (aircraft only).
	struct FRenderLabelledObject
	{
		FString Id;
		int32 IntId = 0;
		int32 ClassId = 0;
		FString Class;
		FString Role;
		AActor* Actor = nullptr;
		USceneCaptureComponent2D* Alone = nullptr;
	};

	// -- Phase 10, P10-4: SHA-256 of what was written -----------------------
	// Self-contained (FIPS 180-4), so the digest recorded in render.json
	// depends on no engine hashing API that a version could move; the
	// Python side hashes the same bytes with hashlib and they must agree.
	constexpr uint32 RenderSha256K[64] = {
		0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u,
		0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u,
		0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
		0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u, 0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u,
		0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u,
		0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
		0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
		0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u, 0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u};

	FORCEINLINE uint32 RenderRotr(uint32 x, uint32 n) { return (x >> n) | (x << (32 - n)); }

	FString RenderSha256Hex(const uint8* Data, int64 Length)
	{
		uint32 H[8] = {0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
		               0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u};
		// Padding: the message, a 0x80 byte, zeros to 56 mod 64, then the
		// bit length big-endian.
		const int64 Padded = ((Length + 9 + 63) / 64) * 64;
		TArray<uint8> Message;
		Message.SetNumZeroed(Padded);
		FMemory::Memcpy(Message.GetData(), Data, Length);
		Message[Length] = 0x80;
		const uint64 Bits = static_cast<uint64>(Length) * 8u;
		for (int32 i = 0; i < 8; ++i)
		{
			Message[Padded - 1 - i] = static_cast<uint8>((Bits >> (8 * i)) & 0xffu);
		}
		uint32 W[64];
		for (int64 Chunk = 0; Chunk < Padded; Chunk += 64)
		{
			const uint8* Block = Message.GetData() + Chunk;
			for (int32 i = 0; i < 16; ++i)
			{
				W[i] = (uint32(Block[4 * i]) << 24) | (uint32(Block[4 * i + 1]) << 16)
				     | (uint32(Block[4 * i + 2]) << 8) | uint32(Block[4 * i + 3]);
			}
			for (int32 i = 16; i < 64; ++i)
			{
				const uint32 s0 = RenderRotr(W[i - 15], 7) ^ RenderRotr(W[i - 15], 18) ^ (W[i - 15] >> 3);
				const uint32 s1 = RenderRotr(W[i - 2], 17) ^ RenderRotr(W[i - 2], 19) ^ (W[i - 2] >> 10);
				W[i] = W[i - 16] + s0 + W[i - 7] + s1;
			}
			uint32 a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
			for (int32 i = 0; i < 64; ++i)
			{
				const uint32 S1 = RenderRotr(e, 6) ^ RenderRotr(e, 11) ^ RenderRotr(e, 25);
				const uint32 ch = (e & f) ^ (~e & g);
				const uint32 t1 = h + S1 + ch + RenderSha256K[i] + W[i];
				const uint32 S0 = RenderRotr(a, 2) ^ RenderRotr(a, 13) ^ RenderRotr(a, 22);
				const uint32 maj = (a & b) ^ (a & c) ^ (b & c);
				const uint32 t2 = S0 + maj;
				h = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
			}
			H[0] += a; H[1] += b; H[2] += c; H[3] += d; H[4] += e; H[5] += f; H[6] += g; H[7] += h;
		}
		FString Hex;
		for (int32 i = 0; i < 8; ++i)
		{
			Hex += FString::Printf(TEXT("%08x"), H[i]);
		}
		return Hex;
	}

	bool RenderWriteGrayPng(const FString& Path, const void* Bytes, int64 NumBytes,
	                        int32 Width, int32 Height, int32 BitDepth)
	{
		IImageWrapperModule& Module =
			FModuleManager::LoadModuleChecked<IImageWrapperModule>(TEXT("ImageWrapper"));
		TSharedPtr<IImageWrapper> Png = Module.CreateImageWrapper(EImageFormat::PNG);
		if (!Png.IsValid()
		    || !Png->SetRaw(Bytes, NumBytes, Width, Height, ERGBFormat::Gray, BitDepth))
		{
			return false;
		}
		const TArray64<uint8> Compressed = Png->GetCompressed();
		return Compressed.Num() > 0 && FFileHelper::SaveArrayToFile(Compressed, *Path);
	}

	bool ProjectToPixel(const USceneCaptureComponent2D* Capture, int32 Width,
	                    int32 Height, const FVector& WorldCm, FVector2D& OutPixel)
	{
		OutPixel = FVector2D(-1.0, -1.0);   // defined even when not visible,
		                                    // so the manifest never carries NaN
		const FVector Local =
			Capture->GetComponentTransform().InverseTransformPosition(WorldCm);
		if (Local.X <= 1.0)
		{
			return false;   // behind the camera
		}
		const double HalfWidthTan = FMath::Tan(FMath::DegreesToRadians(Capture->FOVAngle * 0.5));
		const double HalfHeightTan = HalfWidthTan * Height / double(Width);
		OutPixel.X = Width * 0.5 * (1.0 + (Local.Y / Local.X) / HalfWidthTan);
		OutPixel.Y = Height * 0.5 * (1.0 - (Local.Z / Local.X) / HalfHeightTan);
		return OutPixel.X >= 0 && OutPixel.X < Width &&
		       OutPixel.Y >= 0 && OutPixel.Y < Height;
	}

	// A real aircraft mesh, assembled from the converter's manifest: one
	// static mesh for the body and one per control surface, each surface
	// under a hinge scene component at the hinge line the FlightGear model
	// XML states -- the same attach pattern the placeholder boxes use, so
	// UFlightSimSurfaceAnimator drives real geometry through the identical
	// code path Gate 5 measured.
	struct FMeshAirframe
	{
		bool bLoaded = false;
		FString Name;
		FString FdmName;
		FString MeshAirframe;
		FString License;
		FString Repo;
		FString Commit;
		FString Livery = TEXT("default");
		// Manifest version 2 (Camera Phase 2, package A): where the model's
		// origin sits in the ACTOR frame, cm. The converter's vertices are
		// about the model's own origin -- the FDM's visual reference point,
		// by FlightGear's convention -- while the actor origin is the JSBSim
		// structural datum (UJSBSimMovementComponent::UpdateLocalTransforms:
		// StructuralToActor negates X about StructuralFrameOrigin, zero).
		// Attached at the root, the B747 mesh sat 33.7 m (its VRP x =
		// 1327 in) forward of the CG the label describes; the Phase 1
		// initial run report measured 25-30 m along the airframe's axis.
		// A version-1 manifest has no origin: zero, drawn at the datum, and
		// render.json says so under "drawn" so the verifier fails it.
		FVector MeshOriginActorCm = FVector::ZeroVector;
		int32 ManifestVersion = 0;
		FString OriginBasis;
		double Triangles = 0.0;
	};

	bool BuildMeshAirframe(AActor* Aircraft, UFlightSimSurfaceAnimator* Animator,
	                       const FString& ManifestPath, const FString& CardAircraft,
	                       const FString& Livery, FMeshAirframe& Out, FString& Error)
	{
		FString Text;
		if (!FFileHelper::LoadFileToString(Text, *ManifestPath))
		{
			Error = FString::Printf(TEXT("cannot read mesh manifest '%s'"), *ManifestPath);
			return false;
		}
		TSharedPtr<FJsonObject> Manifest;
		TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
		if (!FJsonSerializer::Deserialize(Reader, Manifest) || !Manifest.IsValid())
		{
			Error = FString::Printf(TEXT("'%s' is not valid JSON"), *ManifestPath);
			return false;
		}
		FString Magic;
		Manifest->TryGetStringField(TEXT("magic"), Magic);
		if (Magic != TEXT("flightsim-aircraft-mesh"))
		{
			Error = FString::Printf(TEXT("'%s' is not an aircraft mesh manifest"),
			                        *ManifestPath);
			return false;
		}

		// §1.4, enforced where the pairing actually happens: the mesh's FDM
		// must be the FDM this card flies. "FDM JSBSIM F16 - MODEL F-15" is
		// the failure this repository exists to prevent, and it is prevented
		// here, not in a comment.
		Manifest->TryGetStringField(TEXT("fdm"), Out.FdmName);
		Manifest->TryGetStringField(TEXT("name"), Out.Name);
		Manifest->TryGetStringField(TEXT("mesh_airframe"), Out.MeshAirframe);
		if (Out.FdmName != CardAircraft)
		{
			Error = FString::Printf(
				TEXT("REFUSING the pairing: mesh manifest '%s' is for FDM '%s' ")
				TEXT("but this card flies '%s'. One mesh per airframe flown."),
				*ManifestPath, *Out.FdmName, *CardAircraft);
			return false;
		}
		const TSharedPtr<FJsonObject>* Source = nullptr;
		if (Manifest->TryGetObjectField(TEXT("source"), Source))
		{
			(*Source)->TryGetStringField(TEXT("license_name"), Out.License);
			(*Source)->TryGetStringField(TEXT("repo"), Out.Repo);
			(*Source)->TryGetStringField(TEXT("commit"), Out.Commit);
		}
		if (Out.License.IsEmpty())
		{
			Error = FString::Printf(
				TEXT("mesh manifest '%s' records no license (§3.3); refusing to ")
				TEXT("render an asset whose terms are unrecorded"), *ManifestPath);
			return false;
		}

		FString AssetRoot;
		Manifest->TryGetStringField(TEXT("asset_path_root"), AssetRoot);
		USceneComponent* Root = Aircraft->GetRootComponent();

		// Where the model's origin sits in the actor (manifest version 2).
		double VersionNumber = 0.0;
		Manifest->TryGetNumberField(TEXT("version"), VersionNumber);
		Out.ManifestVersion = static_cast<int32>(VersionNumber);
		const TArray<TSharedPtr<FJsonValue>>* OriginField = nullptr;
		if (Manifest->TryGetArrayField(TEXT("mesh_origin_actor_cm"), OriginField) &&
		    OriginField != nullptr && OriginField->Num() == 3)
		{
			Out.MeshOriginActorCm = FVector((*OriginField)[0]->AsNumber(),
			                                (*OriginField)[1]->AsNumber(),
			                                (*OriginField)[2]->AsNumber());
			Manifest->TryGetStringField(TEXT("mesh_origin_basis"), Out.OriginBasis);
		}
		else
		{
			// Not a refusal: the frames still render, but every mask is
			// offset from its label by the VRP, and render.json's "drawn"
			// object records it so verify's drawn_airframe check FAILS by
			// name rather than the offset being found by eye.
			Out.OriginBasis = TEXT("no mesh_origin_actor_cm in the manifest (version < 2): ")
			                  TEXT("attached at the actor origin, the structural datum");
			UE_LOG(LogFlightSimRender, Warning,
			       TEXT("mesh manifest '%s' (version %d) records no mesh_origin_actor_cm: ")
			       TEXT("the mesh is attached at the actor origin -- the JSBSim structural ")
			       TEXT("datum -- and is drawn offset from its label by the FDM's VRP ")
			       TEXT("(33.7 m forward on the B747). Fix: re-run assets_pipeline/convert.py ")
			       TEXT("on assets/aircraft_config/%s.json (the web app's render flow ")
			       TEXT("re-converts a stale manifest itself) and render again."),
			       *ManifestPath, Out.ManifestVersion, *Out.Name);
		}
		const TSharedPtr<FJsonObject>* TriangleCounts = nullptr;
		if (Manifest->TryGetObjectField(TEXT("triangles"), TriangleCounts) &&
		    TriangleCounts != nullptr && TriangleCounts->IsValid())
		{
			for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : (*TriangleCounts)->Values)
			{
				double Count = 0.0;
				if (Pair.Value.IsValid() && Pair.Value->TryGetNumber(Count))
				{
					Out.Triangles += Count;
				}
			}
		}
		// ONE component at the model's origin; the body and every hinge hang
		// under it. The hinge mids are stated in the same model-about-origin
		// frame as the vertices, so they move with it and each surface stays
		// on its hinge line. FlightSimScenarioWorld's placement (the actor
		// origin that puts the CG on the commanded point) is untouched: this
		// moves the geometry within the actor, not the actor.
		USceneComponent* MeshOrigin = NewObject<USceneComponent>(Aircraft, TEXT("MeshOrigin"));
		MeshOrigin->SetupAttachment(Root);
		MeshOrigin->SetMobility(EComponentMobility::Movable);
		MeshOrigin->RegisterComponent();
		MeshOrigin->SetRelativeLocation(Out.MeshOriginActorCm);

		auto LoadPart = [&](const FString& Part) -> UStaticMesh*
		{
			const FString Path = FString::Printf(TEXT("%s/%s.%s"), *AssetRoot, *Part, *Part);
			return LoadObject<UStaticMesh>(nullptr, *Path);
		};

		UStaticMesh* Body = LoadPart(TEXT("body"));
		if (Body == nullptr)
		{
			Error = FString::Printf(
				TEXT("mesh asset %s/body did not load. Run the import step ")
				TEXT("(scripts/ue_import_aircraft.py) -- a missing asset must not ")
				TEXT("fall back to the placeholder boxes silently."), *AssetRoot);
			return false;
		}
		UStaticMeshComponent* BodyComponent =
			NewObject<UStaticMeshComponent>(Aircraft, TEXT("MeshBody"));
		BodyComponent->SetupAttachment(MeshOrigin);
		BodyComponent->SetMobility(EComponentMobility::Movable);
		BodyComponent->SetStaticMesh(Body);
		BodyComponent->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		BodyComponent->RegisterComponent();

		// A manifest airframe replaces the whole binding table: its bones are
		// its own (both elevators, split ailerons), and mixing them with the
		// stock table would make bone lookup ambiguous. A scripted traffic
		// actor has no FDM and no animator: its surfaces hang undeflected at
		// their hinges (Phase 2, packages B + C).
		if (Animator != nullptr)
		{
			Animator->ClearBindings();
		}

		const TArray<TSharedPtr<FJsonValue>>* Surfaces = nullptr;
		if (!Manifest->TryGetArrayField(TEXT("surfaces"), Surfaces) || Surfaces == nullptr)
		{
			Error = FString::Printf(TEXT("'%s' has no surfaces"), *ManifestPath);
			return false;
		}
		for (const TSharedPtr<FJsonValue>& Value : *Surfaces)
		{
			const TSharedPtr<FJsonObject>* Entry = nullptr;
			if (!Value->TryGetObject(Entry) || Entry == nullptr)
			{
				Error = TEXT("surfaces must be objects");
				return false;
			}
			FString Bone, Part, Property;
			(*Entry)->TryGetStringField(TEXT("bone"), Bone);
			(*Entry)->TryGetStringField(TEXT("part"), Part);
			(*Entry)->TryGetStringField(TEXT("property"), Property);
			double Scale = 0.0;
			(*Entry)->TryGetNumberField(TEXT("scale_deg_per_unit"), Scale);
			const TArray<TSharedPtr<FJsonValue>>* Hinge = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Axis = nullptr;
			if (!(*Entry)->TryGetArrayField(TEXT("hinge_mid_cm"), Hinge) ||
			    !(*Entry)->TryGetArrayField(TEXT("axis_ue"), Axis) ||
			    Hinge->Num() != 3 || Axis->Num() != 3)
			{
				Error = FString::Printf(TEXT("surface '%s' lacks hinge/axis"), *Bone);
				return false;
			}
			const FVector HingeMid((*Hinge)[0]->AsNumber(), (*Hinge)[1]->AsNumber(),
			                       (*Hinge)[2]->AsNumber());
			const FVector RotationAxis((*Axis)[0]->AsNumber(), (*Axis)[1]->AsNumber(),
			                           (*Axis)[2]->AsNumber());

			UStaticMesh* SurfaceMesh = LoadPart(Part);
			if (SurfaceMesh == nullptr)
			{
				Error = FString::Printf(TEXT("mesh asset %s/%s did not load"),
				                        *AssetRoot, *Part);
				return false;
			}
			USceneComponent* HingeComponent = NewObject<USceneComponent>(
				Aircraft, *FString::Printf(TEXT("%sHinge"), *Bone));
			HingeComponent->SetupAttachment(MeshOrigin);
			HingeComponent->SetMobility(EComponentMobility::Movable);
			HingeComponent->RegisterComponent();
			HingeComponent->SetRelativeLocation(HingeMid);

			UStaticMeshComponent* SurfaceComponent = NewObject<UStaticMeshComponent>(
				Aircraft, *FString::Printf(TEXT("%sMesh"), *Bone));
			SurfaceComponent->SetupAttachment(HingeComponent);
			SurfaceComponent->SetMobility(EComponentMobility::Movable);
			SurfaceComponent->SetStaticMesh(SurfaceMesh);
			SurfaceComponent->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			SurfaceComponent->RegisterComponent();
			// The surface OBJ is exported in place (actor frame); parenting it
			// to a hinge at HingeMid means offsetting it back by the same.
			SurfaceComponent->SetRelativeLocation(-HingeMid);

			bool bContinuous = false;
			(*Entry)->TryGetBoolField(TEXT("continuous"), bContinuous);
			if (Animator != nullptr)
			{
				Animator->AddBinding(Property, FName(*Bone),
				                     static_cast<float>(Scale), RotationAxis,
				                     bContinuous);
				Animator->BindSurfaceComponent(FName(*Bone), HingeComponent);
			}
		}
		// Phase 10 (package 7): the sampled livery. "default" is the
		// mesh's own materials (exactly the previous behaviour); any
		// other name is a material asset the import step placed at
		// <asset_path_root>/Liveries/<name>, applied to every slot of
		// every part. A name that does not load REFUSES by name: a
		// frame whose record says one livery while the pixels show
		// another is the failure this exists to prevent.
		if (!Livery.IsEmpty() && Livery != TEXT("default"))
		{
			const FString LiveryPath = FString::Printf(
				TEXT("%s/Liveries/%s.%s"), *AssetRoot, *Livery, *Livery);
			UMaterialInterface* LiveryMaterial =
				LoadObject<UMaterialInterface>(nullptr, *LiveryPath);
			if (LiveryMaterial == nullptr)
			{
				Error = FString::Printf(
					TEXT("livery '%s' did not load at %s (card randomization.livery); ")
					TEXT("refusing to render the default livery under a record that ")
					TEXT("names another"), *Livery, *LiveryPath);
				return false;
			}
			TInlineComponentArray<UStaticMeshComponent*> Parts;
			Aircraft->GetComponents(Parts);
			int32 Slots = 0;
			for (UStaticMeshComponent* Part : Parts)
			{
				for (int32 Slot = 0; Slot < Part->GetNumMaterials(); ++Slot)
				{
					Part->SetMaterial(Slot, LiveryMaterial);
					++Slots;
				}
			}
			UE_LOG(LogFlightSimRender, Display,
			       TEXT("livery '%s' applied to %d material slot(s) of %d part(s)"),
			       *Livery, Slots, Parts.Num());
		}
		Out.Livery = Livery.IsEmpty() ? TEXT("default") : Livery;
		Out.bLoaded = true;
		UE_LOG(LogFlightSimRender, Display,
		       TEXT("mesh airframe '%s' (%s) [%s, %s@%s]: %d surfaces bound; ")
		       TEXT("manifest version %d, origin (%.1f, %.1f, %.1f) cm in the actor frame"),
		       *Out.Name, *Out.MeshAirframe, *Out.License, *Out.Repo,
		       *Out.Commit.Left(12), Surfaces->Num(), Out.ManifestVersion,
		       Out.MeshOriginActorCm.X, Out.MeshOriginActorCm.Y, Out.MeshOriginActorCm.Z);
		return true;
	}

	FPlaceholderAirframe BuildAirframe(AActor* Aircraft, UStaticMesh* Cube)
	{
		USceneComponent* Root = Aircraft->GetRootComponent();
		FPlaceholderAirframe Frame;

		// Roughly to 747-400 scale: 70 m long, 64 m span, tail 30 m aft.
		AddBox(Aircraft, Root, TEXT("Fuselage"), Cube,
		       FVector(0.0, 0.0, 0.0), FVector(70.0, 6.0, 6.0));
		AddBox(Aircraft, Root, TEXT("Wing"), Cube,
		       FVector(-2.0, 0.0, -1.0), FVector(10.0, 64.0, 1.2));
		AddBox(Aircraft, Root, TEXT("Tailplane"), Cube,
		       FVector(-30.0, 0.0, 1.0), FVector(6.0, 22.0, 1.0));
		AddBox(Aircraft, Root, TEXT("Fin"), Cube,
		       FVector(-29.0, 0.0, 6.0), FVector(7.0, 1.0, 10.0));

		// Ailerons hinge about the span axis, outboard on the trailing edge.
		Frame.LeftAileronHinge = AddHingedSurface(
			Aircraft, Root, TEXT("AileronLeftHinge"), TEXT("AileronLeft"), Cube,
			FVector(-7.0, -22.0, -1.0), FVector(3.0, 14.0, 0.8),
			FVector(-1.5, 0.0, 0.0));
		Frame.RightAileronHinge = AddHingedSurface(
			Aircraft, Root, TEXT("AileronRightHinge"), TEXT("AileronRight"), Cube,
			FVector(-7.0, 22.0, -1.0), FVector(3.0, 14.0, 0.8),
			FVector(-1.5, 0.0, 0.0));
		Frame.ElevatorHinge = AddHingedSurface(
			Aircraft, Root, TEXT("ElevatorHinge"), TEXT("Elevator"), Cube,
			FVector(-33.0, 0.0, 1.0), FVector(3.0, 22.0, 0.8),
			FVector(-1.5, 0.0, 0.0));
		Frame.RudderHinge = AddHingedSurface(
			Aircraft, Root, TEXT("RudderHinge"), TEXT("Rudder"), Cube,
			FVector(-32.5, 0.0, 6.0), FVector(3.0, 0.9, 10.0),
			FVector(-1.5, 0.0, 0.0));
		return Frame;
	}
}

UFlightSimRenderCommandlet::UFlightSimRenderCommandlet()
{
	// The whole point of this class. Without it the engine comes up with a null
	// RHI and every capture writes a blank frame -- which would look like
	// evidence and be nothing of the kind.
	IsClient = true;
	IsEditor = true;
	IsServer = false;
	LogToConsole = true;
	ShowErrorCount = true;
}

int32 UFlightSimRenderCommandlet::Main(const FString& Params)
{
	FString ScenarioPath;
	FString OutputDirectory;
	if (!FParse::Value(*Params, TEXT("scenario="), ScenarioPath) ||
	    !FParse::Value(*Params, TEXT("frames="), OutputDirectory))
	{
		UE_LOG(LogFlightSimRender, Error,
		       TEXT("usage: -run=FlightSimBridge.FlightSimRender ")
		       TEXT("-scenario=<run-card.json> -frames=<out-dir> [-fps=5] [-labels] [-linear] [-deterministic] "
		            "[-width=960] [-height=540]"));
		return 1;
	}
	double FramesPerSecond = 5.0;
	int32 Width = 960;
	int32 Height = 540;
	FParse::Value(*Params, TEXT("fps="), FramesPerSecond);
	FParse::Value(*Params, TEXT("width="), Width);
	FParse::Value(*Params, TEXT("height="), Height);

	// Gate 6 controls. -Visual builds the §6.6 scene; the A/B switches exist
	// so the harness can null-test shadows and the aircraft's presence, and
	// -seconds shortens the run for pixel-aligned stills (physics is
	// deterministic per spec, so equal-length runs land frame-for-frame).
	const bool bVisual = FParse::Param(*Params, TEXT("Visual"));
	// Two framings, because no single camera holds both Gate 6 shadow
	// clauses: the ridge and its shadow band live kilometres ahead, and the
	// aircraft's own shadow lands hundreds of metres from the aircraft --
	// visible only from a high chase looking down. Which sun goes with which
	// shot is part of the framing, and both are recorded in the manifest.
	FString Shot = TEXT("terrain");
	FParse::Value(*Params, TEXT("shot="), Shot);
	const bool bShadowShot = Shot == TEXT("shadow");
	const bool bNoShadows = FParse::Param(*Params, TEXT("NoShadows"));
	const bool bHideAircraft = FParse::Param(*Params, TEXT("HideAircraft"));
	// Phase 10 labels: the engine half of the per-frame ground truth --
	// an instance mask, a class mask, 16-bit depth and an occlusion
	// fraction beside every delivered frame. Opt-in: without it this
	// pass is byte-for-byte the previous one.
	const bool bLabels = FParse::Param(*Params, TEXT("labels"));
	// Phase 10 sensor model: keep the LINEAR frame too. The colour capture
	// is FinalColorLDR into an sRGB8 target -- tone-mapped and quantised
	// -- and the Python post-pass has to invert the transfer to get back
	// to linear light, a stated approximation. -linear adds a second
	// capture of FinalColorHDR into a float target, written as
	// frame_NNNN_linear.exr beside the PNG; the post-pass prefers it when
	// it can read it. Opt-in, additive.
	const bool bLinear = FParse::Param(*Params, TEXT("linear"));
	// Phase 10, P10-4: pin what the renderer would otherwise decide by
	// timing. Texture streaming brings mips in over wall time; LOD
	// selection is deterministic in screen size but a forced LOD takes
	// the question away. Temporal accumulation is handled by the fixed
	// warm-up captures and an identical capture sequence, and Gate 10-R
	// measures whether that is enough rather than assuming it.
	const bool bDeterministic = FParse::Param(*Params, TEXT("deterministic"));
	if (bDeterministic)
	{
		struct FPin { const TCHAR* Name; int32 Value; };
		const FPin Pins[] = {
			{TEXT("r.TextureStreaming"), 0},
			{TEXT("r.Streaming.FullyLoadUsedTextures"), 1},
			{TEXT("r.ForceLOD"), 0},
		};
		for (const FPin& Pin : Pins)
		{
			if (IConsoleVariable* Variable = IConsoleManager::Get().FindConsoleVariable(Pin.Name))
			{
				Variable->Set(Pin.Value, ECVF_SetByCode);
				UE_LOG(LogFlightSimRender, Display, TEXT("deterministic: %s = %d"), Pin.Name, Pin.Value);
			}
			else
			{
				UE_LOG(LogFlightSimRender, Warning,
				       TEXT("deterministic: console variable %s not found in this build"), Pin.Name);
			}
		}
	}
	// The exposure clause's negative control: render with the default
	// auto-exposure so the harness can prove its metric actually catches
	// metering that responds to the scene. A metric no failure can trip is
	// not a measurement (§1.7).
	const bool bAutoExposure = FParse::Param(*Params, TEXT("AutoExposure"));
	FString TerrainPath;
	FParse::Value(*Params, TEXT("terrain="), TerrainPath);
	double SecondsOverride = 0.0;
	FParse::Value(*Params, TEXT("seconds="), SecondsOverride);
	// Full-run telemetry through the SHARED recorder (the same component
	// the telemetry commandlet and the interactive host use), stamping the
	// FDM's own clock. The web app's aero panel reads this file verbatim.
	FString RunTelemetryPath;
	FParse::Value(*Params, TEXT("telemetry="), RunTelemetryPath);

	// -- Phase 6B controls -------------------------------------------------
	// A real aircraft mesh manifest; absent means the placeholder boxes,
	// byte-for-byte as Gate 5 measured them.
	FString MeshManifestPath;
	FParse::Value(*Params, TEXT("mesh="), MeshManifestPath);
	// Georeferenced single-instance terrain at its true position.
	const bool bGeorefTerrain = FParse::Param(*Params, TEXT("GeorefTerrain"));
	// Sun as a time-of-day parameter (dawn / noon / low sun are elevation and
	// azimuth choices made by the harness and recorded in the manifest).
	double SunElevationDeg = 0.0, SunAzimuthDeg = 0.0;
	// Not const since Phase 2: the card's look block (below) overrides the
	// pair when it carries a sun.
	bool bSunOverride =
		FParse::Value(*Params, TEXT("sun-elev="), SunElevationDeg) &&
		FParse::Value(*Params, TEXT("sun-azim="), SunAzimuthDeg);
	// Sun ANIMATION (Phase 7 3.1): end-of-clip elevation/azimuth. The sun
	// interpolates linearly over the clip -- a presentation parameter like
	// the static sun, recorded start and end in the manifest. Requires the
	// static override as the start point.
	double SunElevationEndDeg = 0.0, SunAzimuthEndDeg = 0.0;
	const bool bSunAnimated = bSunOverride &&
		FParse::Value(*Params, TEXT("sun-elev-end="), SunElevationEndDeg) &&
		FParse::Value(*Params, TEXT("sun-azim-end="), SunAzimuthEndDeg);
	double FogDensity = 0.0025;
	FParse::Value(*Params, TEXT("fog-density="), FogDensity);
	// True-colour imagery drape (Phase 7 1.1): path to the drape sidecar
	// produced and verified by core/terrain/imagery.py. Replaces the
	// approximated classification for the real locations.
	FString ImagerySidecar;
	FParse::Value(*Params, TEXT("imagery="), ImagerySidecar);
	double ExposureBias = 11.0;
	FParse::Value(*Params, TEXT("exposure-bias="), ExposureBias);
	// -- Phase 2 Look lane PROBE flags (contracts §5.4, §10) ---------------
	// The look reaches the engine on the CARD (look / randomization.look,
	// core/scene/weather_visuals.py); these flags exist for the Gate 6
	// control renders (one control per switch, the gotcha 6 pattern) and
	// OVERRIDE the card's row when given. Each is recorded in
	// render.json look_applied as a probe override. -stars / -moon are
	// accepted so a request for them is recorded as "not modelled" rather
	// than silently ignored.
	double CloudCoverFlag = -1.0, CloudBaseFlag = -1.0, CloudThicknessFlag = -1.0;
	FParse::Value(*Params, TEXT("cloud-cover="), CloudCoverFlag);
	FParse::Value(*Params, TEXT("cloud-base="), CloudBaseFlag);
	FParse::Value(*Params, TEXT("cloud-thickness="), CloudThicknessFlag);
	double AerosolFlag = -1.0;
	FParse::Value(*Params, TEXT("aerosol="), AerosolFlag);
	FString PrecipFlag;
	FParse::Value(*Params, TEXT("precip="), PrecipFlag);
	const bool bStarsFlag = FParse::Param(*Params, TEXT("stars"));
	const bool bMoonFlag = FParse::Param(*Params, TEXT("moon"));
	// Chase offset override, metres: a 747 framed at -170 m puts a Cessna
	// eleven pixels wide; the harness knows the airframe, so it chooses.
	FString ChaseSpec;
	FParse::Value(*Params, TEXT("chase="), ChaseSpec);
	// The orographic null-test control: same card, coupling severed.
	const bool bNoOrographic = FParse::Param(*Params, TEXT("NoOrographic"));

	if (GDynamicRHI == nullptr || !FApp::CanEverRender())
	{
		UE_LOG(LogFlightSimRender, Error,
		       TEXT("the engine came up without a renderer. Run with "
		            "-RenderOffScreen -AllowCommandletRendering, and without "
		            "-nullrhi. A capture taken now would write a blank frame "
		            "that looks exactly like evidence."));
		return 1;
	}
	UE_LOG(LogFlightSimRender, Display, TEXT("RHI: %s"), GDynamicRHI->GetName());

	FFlightSimScenarioCard Card;
	FString Error;
	if (!FFlightSimScenarioWorld::ReadCard(ScenarioPath, Card, Error))
	{
		UE_LOG(LogFlightSimRender, Error, TEXT("%s"), *Error);
		return 1;
	}
	if (bNoOrographic)
	{
		// The null-test control severs the terrain-wind coupling and nothing
		// else. Recorded in the manifest so the control run cannot be quoted
		// as the coupled one.
		Card.bOrographic = false;
	}

	UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
	if (Cube == nullptr)
	{
		UE_LOG(LogFlightSimRender, Error, TEXT("/Engine/BasicShapes/Cube.Cube did not load"));
		return 1;
	}

	FFlightSimScenarioWorld Scenario;
	auto Fail = [&Scenario](const FString& Why) -> int32
	{
		UE_LOG(LogFlightSimRender, Error, TEXT("%s"), *Why);
		Scenario.Teardown();
		return 1;
	};
	if (!Scenario.Build(Card, Error)) { return Fail(Error); }
	UWorld* World = Scenario.World;

	// -- what makes it visible ---------------------------------------------
	// Two scene tiers. Gate 5's is a deliberately black void: the silhouette
	// measurements depend on it, so it stays byte-for-byte as it was. Gate 6's
	// is the §6.6 scene, behind -Visual.
	FFlightSimVisualScene VisualScene;
	// -- Phase 2 Look lane: the card's look block (contracts §5.4) ---------
	// The engine consumes what the CARD carries: `look` at the root, else
	// `randomization.look` (where package F lands it, contracts §5.6). The
	// keys are exactly core/scene/weather_visuals.py's: fog_extinction_per_m
	// (-> FogDensity, overriding -fog-density), aerosol (RECORDED, not
	// applied: the fog row carries that extinction), clouds[{cover, base_m,
	// top_m}], precipitation + wetness, cloud_drift_mps / cloud_drift_from_deg
	// (recorded, not applied), ev100{camera_id} and the sun pair. A card
	// without the block renders byte-identically to Phase 10 from the flags.
	TSharedPtr<FJsonObject> CardLook;
	FString LookSource = TEXT("flags (the card carries no look block)");
	TMap<FString, double> LookEv100;
	double LookAerosol = 0.0;
	bool bLookAerosol = false;
	{
		FString LookCardText;
		TSharedPtr<FJsonObject> LookCardRoot;
		if (FFileHelper::LoadFileToString(LookCardText, *ScenarioPath))
		{
			const TSharedRef<TJsonReader<>> LookReader =
				TJsonReaderFactory<>::Create(LookCardText);
			FJsonSerializer::Deserialize(LookReader, LookCardRoot);
		}
		const TSharedPtr<FJsonObject>* LookField = nullptr;
		const TSharedPtr<FJsonObject>* RandomizationField = nullptr;
		if (LookCardRoot.IsValid() &&
		    LookCardRoot->TryGetObjectField(TEXT("look"), LookField) &&
		    LookField != nullptr && LookField->IsValid())
		{
			CardLook = *LookField;
			LookSource = TEXT("card.look");
		}
		else if (LookCardRoot.IsValid() &&
		         LookCardRoot->TryGetObjectField(TEXT("randomization"), RandomizationField) &&
		         RandomizationField != nullptr && RandomizationField->IsValid() &&
		         (*RandomizationField)->TryGetObjectField(TEXT("look"), LookField) &&
		         LookField != nullptr && LookField->IsValid())
		{
			CardLook = *LookField;
			LookSource = TEXT("card.randomization.look");
		}
		if (CardLook.IsValid())
		{
			const TSharedPtr<FJsonObject>* Ev100Json = nullptr;
			if (CardLook->TryGetObjectField(TEXT("ev100"), Ev100Json) && Ev100Json != nullptr &&
			    Ev100Json->IsValid())
			{
				for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : (*Ev100Json)->Values)
				{
					double Value = 0.0;
					if (Pair.Value.IsValid() && Pair.Value->TryGetNumber(Value))
					{
						LookEv100.Add(Pair.Key, Value);
					}
				}
			}
			bLookAerosol = CardLook->TryGetNumberField(TEXT("aerosol"), LookAerosol);
		}
	}
	TArray<FString> LookProbeOverrides;
	if (bVisual)
	{
		FFlightSimVisualSceneOptions SceneOptions;
		SceneOptions.TerrainPath = TerrainPath;
		SceneOptions.bDynamicShadows = !bNoShadows;
		SceneOptions.FogDensity = static_cast<float>(FogDensity);
		if (CardLook.IsValid())
		{
			double Value = 0.0;
			if (CardLook->TryGetNumberField(TEXT("fog_extinction_per_m"), Value) && Value > 0.0)
			{
				FogDensity = Value;
				SceneOptions.FogDensity = static_cast<float>(Value);
			}
			double LookSunElevation = 0.0, LookSunAzimuth = 0.0;
			if (!bSunAnimated &&
			    CardLook->TryGetNumberField(TEXT("sun_elevation_deg"), LookSunElevation) &&
			    CardLook->TryGetNumberField(TEXT("engine_sun_azimuth_deg"), LookSunAzimuth))
			{
				// The same pair the flags carry (render_look builds both from
				// one block); the card is the record of truth when present.
				SunElevationDeg = LookSunElevation;
				SunAzimuthDeg = LookSunAzimuth;
				bSunOverride = true;
			}
			const TArray<TSharedPtr<FJsonValue>>* CloudsJson = nullptr;
			if (CardLook->TryGetArrayField(TEXT("clouds"), CloudsJson) && CloudsJson != nullptr)
			{
				for (const TSharedPtr<FJsonValue>& Entry : *CloudsJson)
				{
					const TSharedPtr<FJsonObject> LayerJson =
						Entry.IsValid() ? Entry->AsObject() : nullptr;
					if (!LayerJson.IsValid())
					{
						continue;
					}
					FFlightSimCloudLayer Layer;
					LayerJson->TryGetNumberField(TEXT("cover"), Layer.CoverFraction);
					LayerJson->TryGetNumberField(TEXT("base_m"), Layer.BaseMetres);
					LayerJson->TryGetNumberField(TEXT("top_m"), Layer.TopMetres);
					SceneOptions.CloudLayers.Add(Layer);
				}
			}
			FString Word;
			if (CardLook->TryGetStringField(TEXT("precipitation"), Word))
			{
				SceneOptions.Precipitation = Word;
			}
			if (CardLook->TryGetNumberField(TEXT("wetness"), Value))
			{
				SceneOptions.Wetness = Value;
			}
			CardLook->TryGetNumberField(TEXT("cloud_drift_mps"), SceneOptions.CloudDriftMps);
			CardLook->TryGetNumberField(TEXT("cloud_drift_from_deg"), SceneOptions.CloudDriftFromDeg);
		}
		// Probe overrides (Gate 6 controls), each recorded by name.
		if (CloudCoverFlag >= 0.0)
		{
			SceneOptions.CloudLayers.Reset();
			if (CloudCoverFlag > 0.0)
			{
				FFlightSimCloudLayer Layer;
				Layer.CoverFraction = CloudCoverFlag;
				// The same stated defaults as weather_visuals.py
				// (DEFAULT_CLOUD_BASE_M 1500, DEFAULT_CLOUD_THICKNESS_M 1000).
				Layer.BaseMetres = CloudBaseFlag >= 0.0 ? CloudBaseFlag : 1500.0;
				Layer.TopMetres = Layer.BaseMetres +
					(CloudThicknessFlag > 0.0 ? CloudThicknessFlag : 1000.0);
				SceneOptions.CloudLayers.Add(Layer);
			}
			LookProbeOverrides.Add(TEXT("cloud-cover"));
		}
		if (AerosolFlag >= 0.0)
		{
			SceneOptions.AerosolMieScale = AerosolFlag;
			LookProbeOverrides.Add(TEXT("aerosol"));
		}
		if (!PrecipFlag.IsEmpty())
		{
			// The wetness per word restates weather_visuals.WETNESS
			// (none 0, rain 1.0, snow 0.6); the applied number is recorded.
			if (PrecipFlag == TEXT("none")) { SceneOptions.Wetness = 0.0; }
			else if (PrecipFlag == TEXT("rain")) { SceneOptions.Wetness = 1.0; }
			else if (PrecipFlag == TEXT("snow")) { SceneOptions.Wetness = 0.6; }
			else
			{
				return Fail(FString::Printf(
					TEXT("look.precipitation: -precip='%s' is not one of none|rain|snow"),
					*PrecipFlag));
			}
			SceneOptions.Precipitation = PrecipFlag;
			LookProbeOverrides.Add(TEXT("precip"));
		}
		SceneOptions.bStarsRequested = bStarsFlag;
		SceneOptions.bMoonRequested = bMoonFlag;
		if (bStarsFlag) { LookProbeOverrides.Add(TEXT("stars")); }
		if (bMoonFlag) { LookProbeOverrides.Add(TEXT("moon")); }
		if (bGeorefTerrain)
		{
			SceneOptions.bGeoreferenced = true;
			SceneOptions.GeoReferencing = Scenario.GeoReferencing;
			SceneOptions.bClassifiedMaterial = true;
			SceneOptions.ImagerySidecarPath = ImagerySidecar;
		}
		else if (!ImagerySidecar.IsEmpty())
		{
			return Fail(TEXT("-imagery requires -GeorefTerrain: the drape is "
			                 "aligned to the georeferenced raster grid"));
		}
		// The aircraft flies toward -Y in the engine frame (measured off the
		// first probe's landmark projections; heading north maps there through
		// the plugin's yaw-90 convention). The ridge goes ahead of it, and the
		// far copy at extinction distance beyond.
		SceneOptions.NearTerrainOriginMetres = FVector2D(-8000.0, -21360.0);
		SceneOptions.FarTerrainOriginMetres = FVector2D(-8000.0, -41360.0);
		// Terrain shot: sun beyond the ridge, so the peaks throw their shadow
		// band back across the plain toward the camera. Shadow shot: sun high
		// behind the camera's right shoulder, so the aircraft's shadow lands
		// a few hundred metres ahead-left, inside the downward framing.
		// Terrain shot: side light (from +X), so slopes are lit and every
		// peak throws a measurable shadow across the valley beside it --
		// backlighting turned the whole range into silhouette and there was
		// nothing for the shadow A/B to measure. Shadow shot: sun almost
		// astern, so the aircraft's shadow lands near-centre ahead.
		SceneOptions.SunRotation = bShadowShot
			? FRotator(-40.0, -140.0, 0.0)
			: FRotator(-12.0, 180.0, 0.0);   // low sun: long cast shadows
		if (bSunOverride)
		{
			// Time of day as a parameter: pitch is -elevation, yaw is the
			// direction the LIGHT TRAVELS (sun azimuth + 180), both recorded
			// in the manifest as the approximation they are.
			SceneOptions.SunRotation =
				FRotator(-SunElevationDeg, SunAzimuthDeg + 180.0, 0.0);
		}
		if (!VisualScene.Build(World, SceneOptions, Error)) { return Fail(Error); }
	}
	else
	{
		ADirectionalLight* Sun = World->SpawnActor<ADirectionalLight>();
		Sun->GetLightComponent()->SetMobility(EComponentMobility::Movable);
		Sun->SetActorRotation(FRotator(-35.0, 140.0, 0.0));
		Sun->GetLightComponent()->SetIntensity(8.0f);

		ASkyLight* Sky = World->SpawnActor<ASkyLight>();
		Sky->GetLightComponent()->SetMobility(EComponentMobility::Movable);
		Sky->GetLightComponent()->SetIntensity(1.1f);

		// ...and a fill from the opposite hemisphere, because in this scene
		// that SkyLight delivers NOTHING. Its source is the captured scene,
		// and the scene is a deliberately black void: it captures black and
		// adds black. So the airframe was lit from exactly one direction,
		// and every surface facing away from the sun rendered at 13/255 --
		// the background's own noise floor, below the 24 that separates
		// aircraft from void. Measured on the tower camera, which looks UP
		// at the belly from 68 deg below: 18 of 24 frames came back with
		// literally nothing above the background, while the solved pose had
		// the aircraft dead centre (648, 360) and 25 px across the whole
		// time. The frames were empty because the belly is unlit, not
		// because the camera was aimed wrong.
		//
		// A mirrored key at half intensity is the studio answer: it lights
		// the shadow side to ~65/255 against the sunlit side's ~130, so an
		// observer anywhere on the sphere sees an airframe, and the sun is
		// still visibly the sun. It casts no shadows -- a second shadowing
		// directional light would put a contradictory shadow under the
		// aircraft in the -Visual scene's terms and this tier has no ground
		// to catch one anyway. It cannot brighten the background: a
		// directional light illuminates surfaces, and the void has none.
		ADirectionalLight* Fill = World->SpawnActor<ADirectionalLight>();
		Fill->GetLightComponent()->SetMobility(EComponentMobility::Movable);
		Fill->SetActorRotation(FRotator(35.0, -40.0, 0.0));
		Fill->GetLightComponent()->SetIntensity(4.0f);
		Fill->GetLightComponent()->SetCastShadows(false);
	}

	UFlightSimSurfaceAnimator* Animator =
		NewObject<UFlightSimSurfaceAnimator>(Scenario.Aircraft, TEXT("Surfaces"));
	Animator->Movement = Scenario.Movement;
	Animator->RegisterComponent();

	FMeshAirframe MeshAirframe;
	if (!MeshManifestPath.IsEmpty())
	{
		if (!BuildMeshAirframe(Scenario.Aircraft, Animator, MeshManifestPath,
		                       Card.Aircraft, Card.Livery, MeshAirframe, Error))
		{
			return Fail(Error);
		}
	}
	else
	{
		const FPlaceholderAirframe Frame = BuildAirframe(Scenario.Aircraft, Cube);
		Animator->BindSurfaceComponent(TEXT("elevator"), Frame.ElevatorHinge);
		Animator->BindSurfaceComponent(TEXT("aileron_l"), Frame.LeftAileronHinge);
		Animator->BindSurfaceComponent(TEXT("aileron_r"), Frame.RightAileronHinge);
		Animator->BindSurfaceComponent(TEXT("rudder"), Frame.RudderHinge);
	}
	if (Animator->GetBoundSurfaceCount() == 0)
	{
		return Fail(TEXT("no surface binding is attached to anything; the animator "
		                 "would compute deflections and move nothing"));
	}
	UE_LOG(LogFlightSimRender, Display, TEXT("%d control surfaces bound to geometry"),
	       Animator->GetBoundSurfaceCount());

	// -- Phase 2 (packages B + C): the scripted traffic aircraft -----------
	// Each card traffic entry has a bare actor from Populate; its mesh is
	// built by the SAME BuildMeshAirframe path as the primary's (manifest
	// magic, FDM pairing, licence, at ITS measured mesh origin), with no
	// animator. A traffic entry with no imported mesh refuses by name --
	// placeholder airframes never render, for traffic as for the primary.
	TArray<FMeshAirframe> TrafficMeshes;
	for (int32 Index = 0; Index < Card.Traffic.Num(); ++Index)
	{
		const FFlightSimTrafficTrack& Track = Card.Traffic[Index];
		if (Index >= Scenario.TrafficActors.Num() || Scenario.TrafficActors[Index] == nullptr)
		{
			return Fail(FString::Printf(TEXT("traffic '%s' has no actor in the scenario world"),
			                            *Track.Id));
		}
		if (Track.MeshManifestPath.IsEmpty())
		{
			return Fail(FString::Printf(
				TEXT("aircraft.mesh: traffic '%s' (%s) carries no imported mesh manifest on ")
				TEXT("the card; a scripted traffic actor is drawn from the same imported mesh ")
				TEXT("as a primary would be, never from placeholder boxes"),
				*Track.Id, *Track.Aircraft));
		}
		FMeshAirframe TrafficMesh;
		if (!BuildMeshAirframe(Scenario.TrafficActors[Index], nullptr, Track.MeshManifestPath,
		                       Track.Aircraft, Track.Livery, TrafficMesh, Error))
		{
			return Fail(FString::Printf(TEXT("traffic '%s': %s"), *Track.Id, *Error));
		}
		TrafficMeshes.Add(TrafficMesh);
	}

	// A lagged chase that never inherits roll (§1.5). The previous build welded
	// the camera to the airframe, which put the camera in the body frame, in
	// which the aircraft is by construction never moving.
	AFlightSimCameraDirector* Director = World->SpawnActor<AFlightSimCameraDirector>();
	Director->Target = Scenario.Aircraft;
	Director->Preset = EFlightSimCameraPreset::LaggedChase;
	// Camera preset (Phase 7 3.3). Every preset keeps the §1.5 rule: the
	// camera never inherits roll unless the preset SAYS it does, and the
	// manifest records which one flew and whether roll was inherited.
	FString CameraPreset = TEXT("chase");
	FParse::Value(*Params, TEXT("camera="), CameraPreset);
	if (CameraPreset == TEXT("wingman"))
	{
		Director->Preset = EFlightSimCameraPreset::Wingman;
		// -wingman-abeam=<metres>: the default 25 m formation slot sits
		// INSIDE a tornado funnel during a core transit (measured: 2 of
		// 660 frames blank, floor refused). A wider slot keeps the
		// camera following the aircraft from outside the vortex; the
		// behind distance scales with it so the aircraft stays framed.
		double AbeamMetres = 0.0;
		if (FParse::Value(*Params, TEXT("wingman-abeam="), AbeamMetres)
		    && AbeamMetres > 0.0)
		{
			Director->WingmanOffsetMetres.Y = AbeamMetres;
			Director->WingmanOffsetMetres.X =
				-FMath::Max(15.0, AbeamMetres * 0.25);
			UE_LOG(LogFlightSimRender, Display,
			       TEXT("wingman abeam widened to %.0f m (behind %.0f m)"),
			       Director->WingmanOffsetMetres.Y,
			       -Director->WingmanOffsetMetres.X);
		}
	}
	else if (CameraPreset == TEXT("tower"))
	{
		Director->Preset = EFlightSimCameraPreset::Tower;
	}
	else if (CameraPreset == TEXT("shoulder"))
	{
		Director->Preset = EFlightSimCameraPreset::CockpitShoulder;
		// ONE rule, Python's (core/capture/poses.py: SHOULDER_OFFSET
		// (-6, -0.5, 1.6) m in the body frame from the CG, unscaled). The
		// span scaling with a 1.3 m z floor that lived here (Phase 7: a
		// c172p probe put the B747-scale offset inside the cabin) placed
		// the legacy preset at a different station from the solved track
		// on every airframe but the B747 (Phase 2 critique). The director's
		// default is applied as-is from the CG (TargetAimPoint) and recorded
		// in render.json render_settings.cockpit_offset_m; a small airframe
		// that wants a different station states it on its camera spec.
		UE_LOG(LogFlightSimRender, Display,
		       TEXT("shoulder camera: body offset (%.2f, %.2f, %.2f) m from the CG, ")
		       TEXT("unscaled (Python's SHOULDER_OFFSET rule)"),
		       Director->ShoulderOffsetMetres.X,
		       Director->ShoulderOffsetMetres.Y,
		       Director->ShoulderOffsetMetres.Z);
	}
	else if (CameraPreset != TEXT("chase"))
	{
		return Fail(FString::Printf(
			TEXT("unknown camera preset '%s' (chase|wingman|tower|shoulder)"),
			*CameraPreset));
	}
	Director->ChaseOffsetMetres = bShadowShot
		? FVector(-400.0f, 0.0f, 200.0f)    // high, looking down at the ground
		: FVector(-170.0f, 0.0f, 16.0f);    // level, terrain and sky in shot
	if (!ChaseSpec.IsEmpty())
	{
		// Colon-separated because FParse::Value stops at a comma (measured:
		// "-chase=-170,0,16" arrives here as "-170").
		TArray<FString> Parts;
		ChaseSpec.ParseIntoArray(Parts, TEXT(":"));
		if (Parts.Num() == 3)
		{
			Director->ChaseOffsetMetres = FVector(
				FCString::Atod(*Parts[0]), FCString::Atod(*Parts[1]),
				FCString::Atod(*Parts[2]));
		}
		else
		{
			return Fail(FString::Printf(
				TEXT("-chase expects x:y:z metres, got '%s'"), *ChaseSpec));
		}
	}
	// Start it where it will settle. A spring-lagged camera that begins at the
	// world origin -- three kilometres below the aircraft -- spends its first
	// seconds catching up, and those frames are of empty sky. They would be
	// written, counted, and prove nothing.
	// Aimed as well as placed: the capture component's transform is pushed to
	// the render thread once per frame, so whatever the camera is pointing at
	// when the first capture goes out is what the first frame shows. Left at
	// the default rotation that is empty sky.
	// The place is the director's own answer (PresetRestingPose): this
	// preset's offset from the CG, the point every preset updates from,
	// by the arithmetic the first Tick will use. A station this block
	// computed itself from the actor origin -- the structural datum,
	// 33.7 m ahead of the B747's CG -- opened every preset-mode chase clip
	// 136 m behind the CG with the position lag dragging it in to 170 m
	// over the first ~1.5 s of written frames (the aircraft a quarter
	// larger and drifting), and put the wingman at the CHASE offset to
	// swing ~220 m into its slot: the transient this block exists to
	// prevent, moved rather than removed.
	{
		FVector Station;
		FRotator Look;
		if (!Director->PresetRestingPose(Station, Look))
		{
			return Fail(TEXT("the camera has no aircraft to start behind"));
		}
		Director->SetActorLocationAndRotation(Station, Look.Quaternion());
	}

	// -- consume-poses mode (Camera Phase 1) -------------------------------
	// A card carrying a "cameras" block was solved in Python
	// (core/capture/poses.py): per-sample positions in local scene metres
	// about the block's own projected origin, aerospace yaw/pitch/roll.
	// This pass consumes ONE camera's track verbatim (-camera-index=N; the
	// harness runs one invocation per camera, each with its own -frames=
	// directory); the presets above keep flying cards without the block,
	// byte-identically. Conversion here is the plugin's own established
	// mapping: ProjectedToEngine for position, actor yaw = true heading
	// - 90 (the aircraft placement convention), pitch/roll as-is.
	bool bConsumePoses = false;
	int32 ConsumedCameraIndex = 0;
	double CameraOriginXMetres = 0.0;
	double CameraOriginYMetres = 0.0;
	// The solved camera's own sensor, so the field of view can follow the
	// solved focal length instead of a hardcoded constant. Camera Phase 2:
	// a manifest that names a lens the frames were not taken through is a
	// plausible fiction, and every label derived from it is wrong at the
	// edges of the frame.
	double CameraSensorWidthMm = 0.0;
	// Known static world points, solved in Python and carried on the card.
	// This commandlet projects them through its OWN ProjectToPixel; the
	// Python verifier projects the same points through the manifest. Two
	// implementations of one projection is the only independent
	// reprojection check in this system.
	TArray<FString> LandmarkNames;
	TArray<FVector> LandmarkProjectedMetres;
	// The capture SCHEDULE: the simulation times this camera is meant to
	// produce an image at, solved in Python. Without it the commandlet
	// wrote every rendered frame at the clip's frame rate and numbered
	// them from zero, so a manifest promising 24 images at scheduled
	// times pointed at the first 24 frames of the run -- real files, the
	// wrong pictures. The count contract has to reach the pixels.
	TArray<double> CaptureTimes;
	int32 NextCapture = 0;
	{
		FParse::Value(*Params, TEXT("camera-index="), ConsumedCameraIndex);
		FString CardText;
		TSharedPtr<FJsonObject> CardRoot;
		if (FFileHelper::LoadFileToString(CardText, *ScenarioPath))
		{
			const TSharedRef<TJsonReader<>> CardReader =
				TJsonReaderFactory<>::Create(CardText);
			FJsonSerializer::Deserialize(CardReader, CardRoot);
		}
		const TArray<TSharedPtr<FJsonValue>>* CamerasJson = nullptr;
		if (CardRoot.IsValid() &&
		    CardRoot->TryGetArrayField(TEXT("cameras"), CamerasJson) &&
		    CamerasJson != nullptr && CamerasJson->Num() > 0)
		{
			if (!CamerasJson->IsValidIndex(ConsumedCameraIndex))
			{
				return Fail(FString::Printf(
					TEXT("-camera-index=%d but the card carries %d camera(s)"),
					ConsumedCameraIndex, CamerasJson->Num()));
			}
			const TSharedPtr<FJsonObject> CameraJson =
				(*CamerasJson)[ConsumedCameraIndex]->AsObject();
			const TSharedPtr<FJsonObject>* PosesJson = nullptr;
			if (!CameraJson.IsValid() ||
			    !CameraJson->TryGetNumberField(TEXT("origin_x_m"), CameraOriginXMetres) ||
			    !CameraJson->TryGetNumberField(TEXT("origin_y_m"), CameraOriginYMetres) ||
			    !CameraJson->TryGetObjectField(TEXT("poses"), PosesJson))
			{
				return Fail(TEXT("cameras block is missing origin_x_m/"
				                 "origin_y_m/poses; refusing to guess the frame"));
			}
			// The output frame and the lens are part of the recorded
			// label. Taking them from the card (where core/capture/poses.py
			// put them) rather than from -width=/-height= and a constant
			// FOVAngle is what makes the manifest describe the pixels that
			// were actually produced.
			double CameraWidthPx = 0.0;
			double CameraHeightPx = 0.0;
			if (!CameraJson->TryGetNumberField(TEXT("width_px"), CameraWidthPx) ||
			    !CameraJson->TryGetNumberField(TEXT("height_px"), CameraHeightPx) ||
			    !CameraJson->TryGetNumberField(TEXT("sensor_width_mm"),
			                                   CameraSensorWidthMm))
			{
				return Fail(TEXT("cameras block is missing width_px/"
				                 "height_px/sensor_width_mm; refusing to "
				                 "render through a lens the manifest does "
				                 "not name"));
			}
			if (CameraWidthPx < 1.0 || CameraHeightPx < 1.0 ||
			    CameraSensorWidthMm <= 0.0)
			{
				return Fail(FString::Printf(
					TEXT("cameras block states a %.0fx%.0f output on a "
					     "%.4f mm sensor; not a camera"),
					CameraWidthPx, CameraHeightPx, CameraSensorWidthMm));
			}
			Width = FMath::RoundToInt(CameraWidthPx);
			Height = FMath::RoundToInt(CameraHeightPx);

			const TArray<TSharedPtr<FJsonValue>>* Times = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Norths = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Easts = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Alts = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Yaws = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Pitches = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Rolls = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Focals = nullptr;
			if (!(*PosesJson)->TryGetArrayField(TEXT("focal_length_mm"),
			                                    Focals))
			{
				return Fail(TEXT("camera pose track is missing "
				                 "focal_length_mm; the field of view is "
				                 "solved, never assumed"));
			}
			if (!(*PosesJson)->TryGetArrayField(TEXT("t_s"), Times) ||
			    !(*PosesJson)->TryGetArrayField(TEXT("north_m"), Norths) ||
			    !(*PosesJson)->TryGetArrayField(TEXT("east_m"), Easts) ||
			    !(*PosesJson)->TryGetArrayField(TEXT("alt_m"), Alts) ||
			    !(*PosesJson)->TryGetArrayField(TEXT("yaw_deg"), Yaws) ||
			    !(*PosesJson)->TryGetArrayField(TEXT("pitch_deg"), Pitches) ||
			    !(*PosesJson)->TryGetArrayField(TEXT("roll_deg"), Rolls))
			{
				return Fail(TEXT("camera pose track is missing one of "
				                 "t_s/north_m/east_m/alt_m/yaw_deg/pitch_deg/"
				                 "roll_deg"));
			}
			const int32 Count = Times->Num();
			if (Norths->Num() != Count || Easts->Num() != Count ||
			    Alts->Num() != Count || Yaws->Num() != Count ||
			    Pitches->Num() != Count || Rolls->Num() != Count ||
			    Focals->Num() != Count)
			{
				return Fail(TEXT("camera pose track arrays disagree about "
				                 "their length; refusing a misaligned track"));
			}
			TArray<double> TrackTimes;
			TArray<FVector> TrackLocations;
			TArray<FRotator> TrackRotations;
			TArray<double> TrackFocalLengthsMm;
			TrackTimes.Reserve(Count);
			TrackLocations.Reserve(Count);
			TrackRotations.Reserve(Count);
			TrackFocalLengthsMm.Reserve(Count);
			for (int32 i = 0; i < Count; ++i)
			{
				TrackTimes.Add((*Times)[i]->AsNumber());
				const FVector Projected(
					CameraOriginXMetres + (*Easts)[i]->AsNumber(),
					CameraOriginYMetres + (*Norths)[i]->AsNumber(),
					(*Alts)[i]->AsNumber());
				FVector Engine;
				Scenario.GeoReferencing->ProjectedToEngine(Projected, Engine);
				TrackLocations.Add(Engine);
				TrackRotations.Add(FRotator(
					(*Pitches)[i]->AsNumber(),
					(*Yaws)[i]->AsNumber() - 90.0,
					(*Rolls)[i]->AsNumber()));
				TrackFocalLengthsMm.Add((*Focals)[i]->AsNumber());
			}
			if (!Director->SetPoseTrack(MoveTemp(TrackTimes),
			                            MoveTemp(TrackLocations),
			                            MoveTemp(TrackRotations),
			                            MoveTemp(TrackFocalLengthsMm),
			                            Error))
			{
				return Fail(Error);
			}

			const TArray<TSharedPtr<FJsonValue>>* CaptureTimesJson = nullptr;
			if (CameraJson->TryGetArrayField(TEXT("capture_times_s"),
			                                 CaptureTimesJson) &&
			    CaptureTimesJson != nullptr)
			{
				for (const TSharedPtr<FJsonValue>& Value : *CaptureTimesJson)
				{
					CaptureTimes.Add(Value->AsNumber());
				}
			}
			if (CaptureTimes.Num() == 0)
			{
				return Fail(TEXT("cameras block carries no capture_times_s; "
				                 "refusing to guess which frames the "
				                 "manifest names"));
			}

			// The card's landmarks, expressed like every other card
			// position: local north/east about this camera block's own
			// projected origin, altitude MSL.
			const TArray<TSharedPtr<FJsonValue>>* LandmarksJson = nullptr;
			if (CardRoot->TryGetArrayField(TEXT("landmarks"), LandmarksJson) &&
			    LandmarksJson != nullptr)
			{
				for (const TSharedPtr<FJsonValue>& Value : *LandmarksJson)
				{
					const TSharedPtr<FJsonObject> Landmark = Value->AsObject();
					if (!Landmark.IsValid())
					{
						continue;
					}
					FString LandmarkName;
					double North = 0.0, East = 0.0, Alt = 0.0;
					if (!Landmark->TryGetStringField(TEXT("name"), LandmarkName) ||
					    !Landmark->TryGetNumberField(TEXT("north_m"), North) ||
					    !Landmark->TryGetNumberField(TEXT("east_m"), East) ||
					    !Landmark->TryGetNumberField(TEXT("alt_m"), Alt))
					{
						return Fail(TEXT("a landmark is missing name/"
						                 "north_m/east_m/alt_m"));
					}
					LandmarkNames.Add(LandmarkName);
					LandmarkProjectedMetres.Add(FVector(
						CameraOriginXMetres + East,
						CameraOriginYMetres + North, Alt));
				}
			}
			bConsumePoses = true;
			UE_LOG(LogFlightSimRender, Display,
			       TEXT("consume-poses: camera %d of %d, %d solved samples"),
			       ConsumedCameraIndex, CamerasJson->Num(), Count);
			// Place the camera at its first solved pose before the warm-up
			// captures, replacing the chase settle-in placement above.
			// "First solved pose" is the track's own start, not t=0: the
			// telemetry recorder's first sample is one step in.
			if (!Director->ApplyPoseAtTime(Director->TrackStartSeconds(),
			                               Error))
			{
				return Fail(Error);
			}
		}
	}

	UTextureRenderTarget2D* RenderTarget = NewObject<UTextureRenderTarget2D>();
	RenderTarget->RenderTargetFormat = RTF_RGBA8_SRGB;
	RenderTarget->ClearColor = FLinearColor::Black;
	RenderTarget->bAutoGenerateMips = false;
	RenderTarget->InitAutoFormat(Width, Height);
	RenderTarget->UpdateResourceImmediate(true);

	USceneCaptureComponent2D* Capture =
		NewObject<USceneCaptureComponent2D>(Director, TEXT("Capture"));
	Capture->SetupAttachment(Director->Camera);
	Capture->SetMobility(EComponentMobility::Movable);
	Capture->TextureTarget = RenderTarget;
	Capture->CaptureSource = ESceneCaptureSource::SCS_FinalColorLDR;
	Capture->bCaptureEveryFrame = false;
	Capture->bCaptureOnMovement = false;
	Capture->bAlwaysPersistRenderingState = true;
	// The void scene frames a silhouette tightly; the visual scene needs the
	// terrain and sky in shot, and §6.6's manual exposure so the image does
	// not re-meter as the bright-ground fraction changes with bank.
	// Preset mode keeps the measured constants. Consume-poses mode takes
	// the field of view from the SOLVED LENS -- horizontal FOV =
	// 2*atan(sensor_width / (2*focal_length)) -- so the intrinsics in the
	// capture manifest describe the frames that were actually rendered.
	// The hardcoded 55 deg differed from the documented default lens
	// (35 mm on a 36 mm sensor, 54.43 deg) by about 7 px 600 px off centre,
	// permanently and in every frame, with nothing checking it.
	Capture->FOVAngle = bVisual ? 55.0f : 24.0f;
	if (bConsumePoses)
	{
		Capture->FOVAngle = static_cast<float>(FMath::RadiansToDegrees(
			2.0 * FMath::Atan(CameraSensorWidthMm /
			                  (2.0 * Director->GetAppliedFocalLengthMm()))));
	}
	// Exposure (Phase 2, contracts §5.4 last row, §10): physical EV100 when
	// the consumed camera carries an exposure triple on the card
	// (cameras[N].exposure {aperture_f, shutter_s, iso}); else the Python-
	// computed look.ev100 for that camera's id; else the Phase 10 bias path,
	// unchanged. -AutoExposure stays the negative control and skips all
	// three. Which path ran is recorded in render_settings.exposure_mode.
	FString ExposureMode = TEXT("auto");
	FString ExposureSource = TEXT("engine default metering");
	double AppliedEv100 = 0.0;
	bool bAppliedEv100 = false;
	{
		double CardApertureF = 0.0, CardShutterS = 0.0, CardIso = 0.0;
		bool bCardExposure = false;
		FString CardCameraId;
		if (bConsumePoses)
		{
			FString ExposureCardText;
			TSharedPtr<FJsonObject> ExposureCardRoot;
			if (FFileHelper::LoadFileToString(ExposureCardText, *ScenarioPath))
			{
				const TSharedRef<TJsonReader<>> ExposureReader =
					TJsonReaderFactory<>::Create(ExposureCardText);
				FJsonSerializer::Deserialize(ExposureReader, ExposureCardRoot);
			}
			const TArray<TSharedPtr<FJsonValue>>* ExposureCameras = nullptr;
			if (ExposureCardRoot.IsValid() &&
			    ExposureCardRoot->TryGetArrayField(TEXT("cameras"), ExposureCameras) &&
			    ExposureCameras != nullptr && ExposureCameras->IsValidIndex(ConsumedCameraIndex))
			{
				const TSharedPtr<FJsonObject> ExposureCamera =
					(*ExposureCameras)[ConsumedCameraIndex]->AsObject();
				const TSharedPtr<FJsonObject>* ExposureJson = nullptr;
				if (ExposureCamera.IsValid())
				{
					ExposureCamera->TryGetStringField(TEXT("camera_id"), CardCameraId);
					if (ExposureCamera->TryGetObjectField(TEXT("exposure"), ExposureJson) &&
					    ExposureJson != nullptr && ExposureJson->IsValid())
					{
						const bool bShape =
							(*ExposureJson)->TryGetNumberField(TEXT("aperture_f"), CardApertureF) &&
							(*ExposureJson)->TryGetNumberField(TEXT("shutter_s"), CardShutterS) &&
							(*ExposureJson)->TryGetNumberField(TEXT("iso"), CardIso);
						if (!bShape || !(CardApertureF > 0.0) || !(CardShutterS > 0.0) ||
						    !(CardIso > 0.0))
						{
							return Fail(FString::Printf(
								TEXT("camera.exposure: cameras[%d].exposure must carry positive ")
								TEXT("aperture_f, shutter_s and iso; refusing to meter from a ")
								TEXT("partial triple"),
								ConsumedCameraIndex));
						}
						bCardExposure = true;
					}
				}
			}
		}
		if (bVisual && !bAutoExposure)
		{
			const double* LookValue =
				CardCameraId.IsEmpty() ? nullptr : LookEv100.Find(CardCameraId);
			if (bCardExposure)
			{
				AppliedEv100 = FFlightSimVisualScene::ApplyPhysicalExposure(
					Capture, CardApertureF, CardShutterS, CardIso);
				bAppliedEv100 = true;
				ExposureMode = TEXT("manual_ev100");
				// Numbers only (gotcha 13): the camera id string stays in the
				// Python-written capture manifest.
				ExposureSource = FString::Printf(
					TEXT("cameras[%d].exposure f/%g, %g s, ISO %g"),
					ConsumedCameraIndex, CardApertureF, CardShutterS, CardIso);
			}
			else if (LookValue != nullptr)
			{
				// A Python-computed EV100 without a triple: N = 1, ISO = 100,
				// t = 2^-EV100 maps back to it exactly (core/capture/exposure.py
				// shutter_for_ev100).
				AppliedEv100 = FFlightSimVisualScene::ApplyPhysicalExposure(
					Capture, 1.0, FMath::Pow(2.0, -*LookValue), 100.0);
				bAppliedEv100 = true;
				ExposureMode = TEXT("manual_ev100");
				ExposureSource = FString::Printf(
					TEXT("look.ev100 for cameras[%d]"), ConsumedCameraIndex);
			}
			else
			{
				FFlightSimVisualScene::ApplyManualExposure(Capture,
					static_cast<float>(ExposureBias));
				ExposureMode = TEXT("manual_bias");
				ExposureSource = FString::Printf(
					TEXT("-exposure-bias=%.1f (AutoExposureBias)"), ExposureBias);
			}
		}
		else if (bVisual)
		{
			ExposureSource = TEXT("-AutoExposure: the negative control");
		}
		else
		{
			ExposureSource = TEXT("void scene (no -Visual): engine default metering");
		}
	}
	if (bNoShadows)
	{
		Capture->ShowFlags.SetDynamicShadows(false);
	}
	if (bHideAircraft)
	{
		Capture->HiddenActors.Add(Scenario.Aircraft);
	}
	Capture->RegisterComponent();

	// -- Phase 2 labels (packages B + C, contracts §1): the ID pass -------
	// The instance mask is an ID IMAGE from the Custom Depth Stencil: every
	// labelled mesh component carries bRenderCustomDepth with its stencil =
	// the card's int_id (r.CustomDepth=3 in DefaultEngine.ini), a post-
	// process material emits SceneTexture:CustomStencil as a flat float, and
	// the capture reads it back as raw floats (RCM_MinMax) into an R32f
	// target -- the same capture/readback path the depth pass uses. Every
	// label capture is AA-free: no anti-aliasing, no temporal history, screen
	// percentage 100, fog/atmosphere/bloom/motion blur/DOF/lens flare/
	// translucency off, bAlwaysPersistRenderingState false. One "alone" ID
	// capture per aircraft object (PRM_UseShowOnlyList, that actor only)
	// generalises Phase 10's aircraft-alone depth pass: visible fraction =
	// pixels in the full ID pass / pixels in the alone pass, integers over
	// integers. Phase 10's depth-agreement mask (|scene - alone| <= 5 cm)
	// is gone: it could not tell two aircraft apart and was never
	// AA-isolated. The ID image keeps the _mask.png name and the primary
	// keeps int_id 1, so every Phase 10 reader stays true on a
	// single-aircraft run.
	UTextureRenderTarget2D* LabelDepthTarget = nullptr;
	UTextureRenderTarget2D* LabelIdTarget = nullptr;
	USceneCaptureComponent2D* LabelDepthAll = nullptr;
	USceneCaptureComponent2D* LabelIdAll = nullptr;
	TArray<FRenderLabelledObject> Labelled;
	int32 LabelPrimaryIntId = 0;
	int32 LabelTerrainIntId = 0;
	FString LabelIdSource;
	if (bLabels)
	{
		if (bHideAircraft)
		{
			return Fail(TEXT("-labels with -HideAircraft: an instance mask of a "
			                 "hidden aircraft is nothing; drop one of them"));
		}
		// The objects, from the card (Python composed them; this pass
		// invents no id). A card written before objects[] existed gets the
		// Phase 10 ids -- 1 the aircraft, 2 everything else -- and
		// render.json says so under labels.id_source.
		if (Card.Objects.Num() > 0)
		{
			LabelIdSource = TEXT("card objects[]");
			for (const FFlightSimSceneObject& Object : Card.Objects)
			{
				FRenderLabelledObject Entry;
				Entry.Id = Object.Id;
				Entry.IntId = Object.IntId;
				Entry.ClassId = Object.ClassId;
				Entry.Class = Object.Class;
				Entry.Role = Object.Role;
				if (Object.Role == TEXT("primary"))
				{
					Entry.Actor = Scenario.Aircraft;
					LabelPrimaryIntId = Object.IntId;
				}
				else if (Object.Role == TEXT("traffic"))
				{
					for (int32 j = 0; j < Card.Traffic.Num() && j < Scenario.TrafficActors.Num(); ++j)
					{
						if (Card.Traffic[j].IntId == Object.IntId)
						{
							Entry.Actor = Scenario.TrafficActors[j];
						}
					}
					if (Entry.Actor == nullptr)
					{
						return Fail(FString::Printf(
							TEXT("annotation.identity: object '%s' (int_id %d) has role traffic ")
							TEXT("but no traffic[] entry on the card carries that int_id"),
							*Object.Id, Object.IntId));
					}
				}
				else if (Object.Class == TEXT("terrain"))
				{
					LabelTerrainIntId = Object.IntId;
				}
				Labelled.Add(Entry);
			}
			if (LabelPrimaryIntId == 0)
			{
				return Fail(TEXT("annotation.identity: the card's objects[] names no primary "
				                 "airframe; the ID image would carry no id for the aircraft "
				                 "that flew"));
			}
		}
		else
		{
			LabelIdSource = TEXT("default ids (card carries no objects[]): 1 the aircraft, "
			                     "2 terrain or other");
			FRenderLabelledObject Primary;
			Primary.Id = FString::Printf(TEXT("aircraft:%s:0"), *Card.Aircraft);
			Primary.IntId = RenderLabelAircraftInstanceId;
			Primary.ClassId = RenderLabelClassAircraft;
			Primary.Class = TEXT("aircraft");
			Primary.Role = TEXT("primary");
			Primary.Actor = Scenario.Aircraft;
			Labelled.Add(Primary);
			FRenderLabelledObject Terrain;
			Terrain.Id = TEXT("terrain");
			Terrain.IntId = RenderLabelClassTerrain;
			Terrain.ClassId = RenderLabelClassTerrain;
			Terrain.Class = TEXT("terrain");
			Terrain.Role = TEXT("scene");
			Labelled.Add(Terrain);
			LabelPrimaryIntId = RenderLabelAircraftInstanceId;
			LabelTerrainIntId = RenderLabelClassTerrain;
		}

		// Every mesh component in the world carries the stencil of the
		// object it belongs to: an aircraft actor's its own int_id, every
		// other mesh (terrain, ground plane, funnel) the terrain's. Editor-
		// only and hidden-in-game components draw in no capture and get none.
		TMap<int32, int32> StencilCounts;
		for (TActorIterator<AActor> It(World); It; ++It)
		{
			int32 IntId = LabelTerrainIntId;
			for (const FRenderLabelledObject& Entry : Labelled)
			{
				if (Entry.Actor != nullptr && Entry.Actor == *It)
				{
					IntId = Entry.IntId;
				}
			}
			if (IntId <= 0)
			{
				continue;
			}
			TInlineComponentArray<UMeshComponent*> Meshes;
			It->GetComponents(Meshes);
			for (UMeshComponent* Mesh : Meshes)
			{
				if (Mesh == nullptr || Mesh->IsEditorOnly() || Mesh->bHiddenInGame)
				{
					continue;
				}
				Mesh->SetRenderCustomDepth(true);
				Mesh->SetCustomDepthStencilValue(IntId);
				StencilCounts.FindOrAdd(IntId)++;
			}
		}
		for (const FRenderLabelledObject& Entry : Labelled)
		{
			const int32* Components = StencilCounts.Find(Entry.IntId);
			UE_LOG(LogFlightSimRender, Display,
			       TEXT("labels: object '%s' int_id %d class_id %d (%s): stencil on %d mesh component(s)"),
			       *Entry.Id, Entry.IntId, Entry.ClassId, *Entry.Role, Components ? *Components : 0);
		}

		UMaterialInterface* StencilMaterial =
			LoadObject<UMaterialInterface>(nullptr, RenderLabelStencilMaterialPath);
		if (StencilMaterial == nullptr)
		{
			return Fail(FString::Printf(
				TEXT("-labels needs the post-process material %s (MD_PostProcess, blendable ")
				TEXT("location 'Replacing the Tonemapper', EmissiveColor = SceneTexture:")
				TEXT("CustomStencil), which scripts/ue_create_materials.py builds; refusing ")
				TEXT("to write an ID image from anything else"),
				RenderLabelStencilMaterialPath));
		}

		LabelDepthTarget = NewObject<UTextureRenderTarget2D>();
		LabelDepthTarget->RenderTargetFormat = RTF_R32f;
		LabelDepthTarget->ClearColor = FLinearColor::Black;
		LabelDepthTarget->bAutoGenerateMips = false;
		LabelDepthTarget->InitAutoFormat(Width, Height);
		LabelDepthTarget->UpdateResourceImmediate(true);
		LabelIdTarget = NewObject<UTextureRenderTarget2D>();
		LabelIdTarget->RenderTargetFormat = RTF_R32f;
		LabelIdTarget->ClearColor = FLinearColor::Black;
		LabelIdTarget->bAutoGenerateMips = false;
		LabelIdTarget->InitAutoFormat(Width, Height);
		LabelIdTarget->UpdateResourceImmediate(true);

		// The label-pass rule (contracts §1, brainstorm §3.3), applied to
		// every label capture: no anti-aliasing of any kind, no temporal
		// history, no screen-percentage scaling, and no effect that blends
		// a pixel with its neighbours or with the air in front of it.
		auto ConfigureLabelCapture = [&](USceneCaptureComponent2D* Label)
		{
			Label->SetupAttachment(Director->Camera);
			Label->SetMobility(EComponentMobility::Movable);
			Label->bCaptureEveryFrame = false;
			Label->bCaptureOnMovement = false;
			Label->bAlwaysPersistRenderingState = false;
			Label->FOVAngle = Capture->FOVAngle;
			Label->ShowFlags.SetAntiAliasing(false);
			Label->ShowFlags.SetTemporalAA(false);
			Label->ShowFlags.SetScreenPercentage(false);
			Label->ShowFlags.SetFog(false);
			Label->ShowFlags.SetAtmosphere(false);
			Label->ShowFlags.SetVolumetricFog(false);
			// Phase 2 Look lane: volumetric clouds write no depth and the ID
			// pass replaces the tonemapper, but a label capture draws no
			// cloud at all (contracts §1, extended by this stage).
			Label->ShowFlags.SetCloud(false);
			Label->ShowFlags.SetBloom(false);
			Label->ShowFlags.SetMotionBlur(false);
			Label->ShowFlags.SetDepthOfField(false);
			Label->ShowFlags.SetLensFlares(false);
			Label->ShowFlags.SetTranslucency(false);
		};
		auto MakeDepthCapture = [&](const TCHAR* Name) -> USceneCaptureComponent2D*
		{
			USceneCaptureComponent2D* Depth =
				NewObject<USceneCaptureComponent2D>(Director, Name);
			Depth->TextureTarget = LabelDepthTarget;
			Depth->CaptureSource = ESceneCaptureSource::SCS_SceneDepth;
			ConfigureLabelCapture(Depth);
			Depth->RegisterComponent();
			return Depth;
		};
		auto MakeIdCapture = [&](const TCHAR* Name) -> USceneCaptureComponent2D*
		{
			USceneCaptureComponent2D* Id =
				NewObject<USceneCaptureComponent2D>(Director, Name);
			Id->TextureTarget = LabelIdTarget;
			// The post-process chain has to run for the blendable to
			// replace the tonemapper; FinalColorHDR keeps its output
			// linear and unquantised, so R is the stencil as a float.
			Id->CaptureSource = ESceneCaptureSource::SCS_FinalColorHDR;
			ConfigureLabelCapture(Id);
			Id->ShowFlags.SetPostProcessing(true);
			Id->PostProcessSettings.WeightedBlendables.Array.Add(
				FWeightedBlendable(1.0f, StencilMaterial));
			Id->PostProcessBlendWeight = 1.0f;
			Id->RegisterComponent();
			return Id;
		};
		LabelDepthAll = MakeDepthCapture(TEXT("LabelDepthAll"));
		LabelIdAll = MakeIdCapture(TEXT("LabelIdAll"));
		for (FRenderLabelledObject& Entry : Labelled)
		{
			if (Entry.Class != TEXT("aircraft") || Entry.Actor == nullptr)
			{
				continue;   // scene objects get no alone pass (pixels_alone null)
			}
			Entry.Alone = MakeIdCapture(*FString::Printf(TEXT("LabelIdAlone%d"), Entry.IntId));
			Entry.Alone->PrimitiveRenderMode =
				ESceneCapturePrimitiveRenderMode::PRM_UseShowOnlyList;
			Entry.Alone->ShowOnlyActors.Add(Entry.Actor);
		}
		UE_LOG(LogFlightSimRender, Display,
		       TEXT("labels: ID image (custom stencil, %d objects, %s), class image, depth ")
		       TEXT("as float32 and 16-bit (%.2f m/unit, saturating at %.1f m), one alone ")
		       TEXT("pass per aircraft; every label capture AA-free"),
		       Labelled.Num(), *LabelIdSource, RenderLabelDepthScaleM,
		       RenderLabelDepthSaturationM);
	}

	// -- Phase 10 sensor model: the linear capture ------------------------
	UTextureRenderTarget2D* LinearTarget = nullptr;
	USceneCaptureComponent2D* LinearCapture = nullptr;
	if (bLinear)
	{
		LinearTarget = NewObject<UTextureRenderTarget2D>();
		LinearTarget->RenderTargetFormat = RTF_RGBA16f;
		LinearTarget->ClearColor = FLinearColor::Black;
		LinearTarget->bAutoGenerateMips = false;
		LinearTarget->InitAutoFormat(Width, Height);
		LinearTarget->UpdateResourceImmediate(true);
		LinearCapture = NewObject<USceneCaptureComponent2D>(Director, TEXT("LinearCapture"));
		LinearCapture->SetupAttachment(Director->Camera);
		LinearCapture->SetMobility(EComponentMobility::Movable);
		LinearCapture->TextureTarget = LinearTarget;
		LinearCapture->CaptureSource = ESceneCaptureSource::SCS_FinalColorHDR;
		LinearCapture->bCaptureEveryFrame = false;
		LinearCapture->bCaptureOnMovement = false;
		LinearCapture->bAlwaysPersistRenderingState = true;
		LinearCapture->FOVAngle = Capture->FOVAngle;
		LinearCapture->ShowFlags = Capture->ShowFlags;
		LinearCapture->PostProcessSettings = Capture->PostProcessSettings;
		LinearCapture->PostProcessBlendWeight = Capture->PostProcessBlendWeight;
		LinearCapture->HiddenActors = Capture->HiddenActors;
		LinearCapture->RegisterComponent();
		UE_LOG(LogFlightSimRender, Display,
		       TEXT("linear: FinalColorHDR written as frame_NNNN_linear.exr beside each frame"));
	}

	if (!Scenario.BeginPlay(Error)) { return Fail(Error); }
	if (!Scenario.TrimInWind(Card, Error)) { return Fail(Error); }
	if (!Scenario.VerifyTrimmedCondition(Card, Error)) { return Fail(Error); }
	Scenario.LatchTrimmedControls(Card.bMassHeld);
	// After trim and latch, once, mirroring EnvironmentStack.configure. The
	// render path accepts turbulence (the seed goes in the manifest); the
	// PARITY path's policy lives in the telemetry commandlet and the harness.
	Scenario.ConfigureTurbulence(Card);

	// The orographic cross-implementation check: sample the C++ field at a
	// fixed grid around the origin and write the values into the manifest.
	// The Python harness recomputes the same points through the original
	// provider over the same raster; a port that drifted fails there.
	TArray<TSharedPtr<FJsonValue>> OrographicSelftest;
	if (const FFlightSimOrographicWind* Orographic = Scenario.GetOrographic())
	{
		const double Offsets[] = {-6000.0, -3000.0, -900.0, 0.0, 900.0, 3000.0, 6000.0};
		const double Agls[] = {120.0, 600.0, 1800.0};
		int32 Index = 0;
		for (double North : Offsets)
		{
			for (double East : Offsets)
			{
				const double Agl = Agls[Index++ % UE_ARRAY_COUNT(Agls)];
				TSharedPtr<FJsonObject> Sample = MakeShared<FJsonObject>();
				Sample->SetNumberField(TEXT("north_m"), North);
				Sample->SetNumberField(TEXT("east_m"), East);
				Sample->SetNumberField(TEXT("agl_m"), Agl);
				Sample->SetNumberField(TEXT("elevation_m"),
				                       Orographic->ElevationMetres(North, East));
				Sample->SetNumberField(TEXT("wind_down_mps"),
				                       Orographic->WindDownMps(North, East, Agl));
				OrographicSelftest.Add(MakeShared<FJsonValueObject>(Sample));
			}
		}
	}

	// The same cross-implementation discipline for every Phase 7 port: grid
	// samples of the C++ field into the manifest, recomputed by the original
	// Python provider in the harness. A port that drifts fails there.
	TArray<TSharedPtr<FJsonValue>> DownburstSelftest;
	if (const FFlightSimDownburst* Burst = Scenario.GetDownburst())
	{
		const double Radii[] = {0.0, 300.0, 700.0, 1000.0, 1400.0, 2500.0};
		const double Agls[] = {30.0, 150.0, 300.0, 600.0};
		for (double Radius : Radii)
		{
			for (double Agl : Agls)
			{
				// Sample along north from the centre; axisymmetry is the
				// field's own claim and the Python recompute checks the full
				// NED vector at these points.
				double NorthMps = 0.0, EastMps = 0.0, DownMps = 0.0;
				Burst->WindNedMps(Burst->CentreNorthMetres + Radius,
				                  Burst->CentreEastMetres, Agl,
				                  NorthMps, EastMps, DownMps);
				TSharedPtr<FJsonObject> Sample = MakeShared<FJsonObject>();
				Sample->SetNumberField(TEXT("radius_m"), Radius);
				Sample->SetNumberField(TEXT("agl_m"), Agl);
				Sample->SetNumberField(TEXT("north_mps"), NorthMps);
				Sample->SetNumberField(TEXT("east_mps"), EastMps);
				Sample->SetNumberField(TEXT("down_mps"), DownMps);
				DownburstSelftest.Add(MakeShared<FJsonValueObject>(Sample));
			}
		}
	}

	TArray<TSharedPtr<FJsonValue>> RotorSelftest;
	if (Scenario.RotorReady())
	{
		const double Offsets[] = {-3000.0, -900.0, 0.0, 900.0, 3000.0};
		const double Agls[] = {60.0, 150.0, 280.0};
		int32 Index = 0;
		for (double North : Offsets)
		{
			for (double East : Offsets)
			{
				const double Agl = Agls[Index++ % UE_ARRAY_COUNT(Agls)];
				TSharedPtr<FJsonObject> Sample = MakeShared<FJsonObject>();
				Sample->SetNumberField(TEXT("north_m"), North);
				Sample->SetNumberField(TEXT("east_m"), East);
				Sample->SetNumberField(TEXT("agl_m"), Agl);
				Sample->SetNumberField(TEXT("w20_fps"),
				                       Scenario.RotorW20Fps(North, East, Agl));
				RotorSelftest.Add(MakeShared<FJsonValueObject>(Sample));
			}
		}
	}

	TArray<TSharedPtr<FJsonValue>> LogProfileSelftest;
	if (Card.bLogProfile)
	{
		const double Agls[] = {0.0, 5.0, 10.0, 30.0, 100.0, 200.0, 300.0, 500.0};
		for (double Agl : Agls)
		{
			TSharedPtr<FJsonObject> Sample = MakeShared<FJsonObject>();
			Sample->SetNumberField(TEXT("agl_m"), Agl);
			Sample->SetNumberField(TEXT("speed_mps"),
			                       Scenario.LogProfileSpeedMps(Agl));
			LogProfileSelftest.Add(MakeShared<FJsonValueObject>(Sample));
		}
	}

	TArray<TSharedPtr<FJsonValue>> ThermalsSelftest;
	if (Scenario.ThermalsReady())
	{
		const double Offsets[] = {-900.0, -300.0, 0.0, 150.0, 300.0, 900.0};
		const double Agls[] = {150.0, 400.0, 900.0};
		int32 Index = 0;
		for (double North : Offsets)
		{
			for (double East : Offsets)
			{
				const double Agl = Agls[Index++ % UE_ARRAY_COUNT(Agls)];
				TSharedPtr<FJsonObject> Sample = MakeShared<FJsonObject>();
				Sample->SetNumberField(TEXT("north_m"), North);
				Sample->SetNumberField(TEXT("east_m"), East);
				Sample->SetNumberField(TEXT("agl_m"), Agl);
				Sample->SetNumberField(TEXT("w_up_mps"),
				                       Scenario.ThermalWMps(North, East, Agl));
				ThermalsSelftest.Add(MakeShared<FJsonValueObject>(Sample));
			}
		}
	}

	if (GShaderCompilingManager != nullptr)
	{
		UE_LOG(LogFlightSimRender, Display, TEXT("waiting for shader compilation"));
		GShaderCompilingManager->FinishAllCompilation();
	}
	// Static meshes above a size threshold build their render data
	// asynchronously, and a commandlet never ticks the compiling manager --
	// so a large imported mesh stays "compiling" forever and draws NOTHING
	// while every capture reports success (measured: the 747 body was absent
	// from every frame while its 26-triangle ailerons rendered fine). Finish
	// the builds before the first capture, exactly as with shaders above.
	FAssetCompilingManager::Get().FinishAllCompilation();

	// Discarded warm-up captures. The first CaptureScene after the component is
	// registered resolves nothing -- the scene proxies exist, but the capture's
	// own rendering state is allocated by the call itself, and measured on this
	// build it takes two calls before a frame comes back with anything in it.
	// Keeping them would put black rectangles at t=0 of every run. They are
	// discarded rather than tolerated: a blank frame in the output is a failure
	// below, and it has to stay one.
	for (int32 i = 0; i < 2; ++i)
	{
		World->SendAllEndOfFrameUpdates();
		FlushRenderingCommands();
		Capture->CaptureScene();
		FlushRenderingCommands();
	}

	// -- Phase 8B.0: the real-time probe loop ------------------------------
	// The interactive host cannot run under a locked console session (both
	// editor binaries park -game mode in the AppKit event loop; sampled), so
	// the go/no-go frame cost is measured HERE: the same scene, the same
	// stepping path, a wall-clock substep accumulator identical to the
	// interactive host's, and one CaptureScene per iteration with NO pixel
	// readback and NO png encode. FlushRenderingCommands serializes the GPU
	// into the measurement, so the number is conservative. What it excludes
	// -- window compositing, slate/HUD draw -- is stated in the report.
	double ProbeWallSeconds = 0.0;
	FParse::Value(*Params, TEXT("probe-wall-seconds="), ProbeWallSeconds);
	if (ProbeWallSeconds > 0.0)
	{
		FString ProbeReportPath;
		FParse::Value(*Params, TEXT("probe-report="), ProbeReportPath);
		// Replay-parity outputs (Gate 8.2, locked-session path): the same
		// recorder the telemetry commandlet uses, sampling on the FDM's own
		// clock while THIS loop paces the FDM by the wall clock -- the
		// stepping and clocking the interactive host uses, minus the window.
		FString ProbeTelemetryPath, ProbeManifestPath;
		FParse::Value(*Params, TEXT("probe-telemetry="), ProbeTelemetryPath);
		FParse::Value(*Params, TEXT("probe-manifest="), ProbeManifestPath);
		UFlightSimTelemetryRecorder* ProbeRecorder = nullptr;
		if (!ProbeTelemetryPath.IsEmpty())
		{
			ProbeRecorder = NewObject<UFlightSimTelemetryRecorder>(
				Scenario.Aircraft, TEXT("ProbeRecorder"));
			ProbeRecorder->Movement = Scenario.Movement;
			ProbeRecorder->SampleIntervalSeconds =
				static_cast<float>(Card.SampleIntervalSeconds);
			ProbeRecorder->RegisterComponent();
			// hazard 1: refuse rather than record NaN forever.
			if (!ProbeRecorder->SelftestProperties(Error))
			{
				return Fail(Error);
			}
			ProbeRecorder->StartRecording(ProbeTelemetryPath);
		}
		const double SubstepSeconds = 1.0 / Card.RateHz;
		const double CatchUpCapSeconds = 0.25;
		double Accumulator = 0.0;
		double SimTime = 0.0;
		double DeficitSeconds = 0.0;
		uint64 Substeps = 0, DeficitEvents = 0;
		TArray<float> ProbeFrameSeconds;
		double WallStart = FPlatformTime::Seconds();
		double LastFrame = WallStart;
		UE_LOG(LogFlightSimRender, Display,
		       TEXT("probe: real-time loop for %.0f s wall at %dx%d"),
		       ProbeWallSeconds, Width, Height);
		while (FPlatformTime::Seconds() - WallStart < ProbeWallSeconds
		       && SimTime < Card.DurationSeconds)
		{
			const double Now = FPlatformTime::Seconds();
			const double WallDelta = Now - LastFrame;
			LastFrame = Now;
			ProbeFrameSeconds.Add(static_cast<float>(WallDelta));
			Accumulator += WallDelta;
			if (Accumulator > CatchUpCapSeconds)
			{
				DeficitEvents += 1;
				DeficitSeconds += Accumulator - CatchUpCapSeconds;
				Accumulator = CatchUpCapSeconds;
			}
			while (Accumulator >= SubstepSeconds)
			{
				if (!Scenario.Step(Card, SimTime, SubstepSeconds, Error))
				{
					return Fail(Error + TEXT("; probe aborted"));
				}
				SimTime += SubstepSeconds;
				Accumulator -= SubstepSeconds;
				++Substeps;
			}
			World->SendAllEndOfFrameUpdates();
			FlushRenderingCommands();
			Capture->CaptureScene();
			FlushRenderingCommands();
		}
		const double WallTotal = FPlatformTime::Seconds() - WallStart;
		if (ProbeRecorder != nullptr && !ProbeRecorder->WriteToDisk())
		{
			return Fail(TEXT("probe telemetry did not write"));
		}
		if (!ProbeManifestPath.IsEmpty())
		{
			TSharedPtr<FJsonObject> Manifest = MakeShared<FJsonObject>();
			Manifest->SetStringField(TEXT("host"),
				TEXT("interactive-equivalent (commandlet wall-clock loop; ")
				TEXT("locked-session path -- no window)"));
			Manifest->SetStringField(TEXT("spec_digest"), Card.SpecDigest);
			Manifest->SetStringField(TEXT("aircraft"), Card.Aircraft);
			Manifest->SetStringField(TEXT("turbulence"), Card.Turbulence);
			Manifest->SetNumberField(TEXT("turbulence_seed"),
			                         static_cast<double>(Card.TurbulenceSeed));
			Manifest->SetNumberField(TEXT("sim_seconds"), SimTime);
			Manifest->SetNumberField(TEXT("wall_seconds"), WallTotal);
			Manifest->SetNumberField(TEXT("substeps"),
			                         static_cast<double>(Substeps));
			Manifest->SetNumberField(TEXT("substep_rate_hz"), Card.RateHz);
			Manifest->SetNumberField(TEXT("deficit_events"),
			                         static_cast<double>(DeficitEvents));
			Manifest->SetNumberField(TEXT("deficit_seconds"), DeficitSeconds);
			Manifest->SetStringField(TEXT("telemetry"), ProbeTelemetryPath);
			FString ManifestPayload;
			const TSharedRef<TJsonWriter<>> ManifestWriter =
				TJsonWriterFactory<>::Create(&ManifestPayload);
			FJsonSerializer::Serialize(Manifest.ToSharedRef(), ManifestWriter);
			FFileHelper::SaveStringToFile(ManifestPayload, *ProbeManifestPath);
		}
		if (!ProbeReportPath.IsEmpty() && ProbeFrameSeconds.Num() > 0)
		{
			TArray<float> Sorted = ProbeFrameSeconds;
			Sorted.Sort();
			auto Percentile = [&Sorted](double P) -> double
			{
				const int32 Index = FMath::Clamp(
					static_cast<int32>(P * (Sorted.Num() - 1)), 0, Sorted.Num() - 1);
				return static_cast<double>(Sorted[Index]);
			};
			TSharedPtr<FJsonObject> Probe = MakeShared<FJsonObject>();
			Probe->SetStringField(TEXT("outcome"), TEXT("probe complete"));
			Probe->SetStringField(TEXT("spec_digest"), Card.SpecDigest);
			Probe->SetStringField(TEXT("aircraft"), Card.Aircraft);
			Probe->SetNumberField(TEXT("frames"), ProbeFrameSeconds.Num());
			Probe->SetNumberField(TEXT("wall_seconds"), WallTotal);
			Probe->SetNumberField(TEXT("fps_mean"),
			                      ProbeFrameSeconds.Num() / WallTotal);
			Probe->SetNumberField(TEXT("frame_ms_p50"), Percentile(0.50) * 1000.0);
			Probe->SetNumberField(TEXT("frame_ms_p95"), Percentile(0.95) * 1000.0);
			Probe->SetNumberField(TEXT("frame_ms_max"),
			                      static_cast<double>(Sorted.Last()) * 1000.0);
			Probe->SetNumberField(TEXT("sim_seconds"), SimTime);
			Probe->SetNumberField(TEXT("substeps"), static_cast<double>(Substeps));
			Probe->SetNumberField(TEXT("substep_rate_hz"), Card.RateHz);
			Probe->SetNumberField(TEXT("deficit_events"),
			                      static_cast<double>(DeficitEvents));
			Probe->SetNumberField(TEXT("deficit_seconds"), DeficitSeconds);
			Probe->SetStringField(TEXT("terrain"), VisualScene.TerrainName);
			Probe->SetStringField(TEXT("terrain_sha256"), VisualScene.TerrainSha256);
			Probe->SetStringField(TEXT("imagery_dataset"), VisualScene.ImageryDataset);
			Probe->SetStringField(TEXT("display"),
				TEXT("offscreen commandlet loop: SceneCapture per frame, no ")
				TEXT("readback; window compositing and HUD draw excluded"));
			Probe->SetStringField(TEXT("airframe"),
				TEXT("as rendered by this commandlet (mesh if -mesh was given)"));
			FString Payload;
			const TSharedRef<TJsonWriter<>> Writer =
				TJsonWriterFactory<>::Create(&Payload);
			FJsonSerializer::Serialize(Probe.ToSharedRef(), Writer);
			FFileHelper::SaveStringToFile(Payload, *ProbeReportPath);
			UE_LOG(LogFlightSimRender, Display, TEXT("probe report -> %s"),
			       *ProbeReportPath);
		}
		Scenario.Teardown();
		return 0;
	}

	// -- the run -----------------------------------------------------------
	UFlightSimTelemetryRecorder* RunRecorder = nullptr;
	if (!RunTelemetryPath.IsEmpty())
	{
		RunRecorder = NewObject<UFlightSimTelemetryRecorder>(
			Scenario.Aircraft, TEXT("RunRecorder"));
		RunRecorder->Movement = Scenario.Movement;
		RunRecorder->SampleIntervalSeconds =
			static_cast<float>(Card.SampleIntervalSeconds);
		RunRecorder->RegisterComponent();
		// hazard 1: refuse rather than record NaN forever.
		if (!RunRecorder->SelftestProperties(Error))
		{
			return Fail(Error);
		}
		RunRecorder->StartRecording(RunTelemetryPath);
	}
	const double DeltaSeconds = 1.0 / Card.RateHz;
	const double Duration = SecondsOverride > 0.0
		? FMath::Min(SecondsOverride, Card.DurationSeconds)
		: Card.DurationSeconds;
	const int32 Steps = FMath::RoundToInt(Duration * Card.RateHz);
	const int32 StepsPerFrame = FMath::Max(1, FMath::RoundToInt(Card.RateHz / FramesPerSecond));
	UE_LOG(LogFlightSimRender, Display,
	       TEXT("stepping %d frames of %.6f s, capturing every %d (%.1f Hz) at %dx%d"),
	       Steps, DeltaSeconds, StepsPerFrame, Card.RateHz / StepsPerFrame, Width, Height);

	TArray<TSharedPtr<FJsonValue>> FrameRecords;
	TArray<FColor> Pixels;
	int32 Captured = 0;
	int32 BlankFrames = 0;

	for (int32 Step = 0; Step < Steps; ++Step)
	{
		const double Time = Step * DeltaSeconds;
		if (!Scenario.Step(Card, Time, DeltaSeconds, Error))
		{
			return Fail(Error + TEXT("; frames written so far are not a complete run"));
		}
		// Consume-poses captures on the SCHEDULE, not on the clip's frame
		// grid. Three things follow from putting the gate here:
		//
		//  * the frame delivered for a scheduled instant is taken within
		//    one SUBSTEP of it (8 ms at 120 Hz) instead of within one
		//    clip frame (200 ms at 5 Hz) -- at cruise that was 30 m of
		//    aircraft motion between what a record says and what its
		//    picture shows;
		//  * the pose is applied only at instants the track covers, so
		//    the host's first frame at t=0 (the recorder's first sample
		//    is one step in) is skipped rather than refused;
		//  * nothing renders that is not going to be written, instead of
		//    rendering the whole clip and discarding all but the
		//    scheduled frames.
		if (bConsumePoses)
		{
			const double Now =
				Scenario.ReadProperty(TEXT("simulation/sim-time-sec"));
			if (NextCapture >= CaptureTimes.Num() ||
			    Now + 0.5 * DeltaSeconds < CaptureTimes[NextCapture])
			{
				continue;
			}
			++NextCapture;
		}
		else if (Step % StepsPerFrame != 0)
		{
			continue;
		}

		// The animated sun (Phase 7 3.1): linear in time across the clip,
		// same convention as the static override (pitch = -elevation, yaw =
		// direction the light TRAVELS).
		if (bSunAnimated && VisualScene.Sun != nullptr && Duration > 0.0)
		{
			const double Fraction = FMath::Clamp(Time / Duration, 0.0, 1.0);
			const double Elev = FMath::Lerp(SunElevationDeg, SunElevationEndDeg, Fraction);
			const double Azim = FMath::Lerp(SunAzimuthDeg, SunAzimuthEndDeg, Fraction);
			VisualScene.Sun->SetActorRotation(FRotator(-Elev, Azim + 180.0, 0.0));
		}

		// Consume-poses: drive the camera by SIMULATION time before the
		// render-state flush, so the capture sees the solved pose for this
		// exact frame. A track that does not cover the run fails loudly
		// here (never extrapolated), as does any applied-vs-solved drift.
		if (bConsumePoses)
		{
			if (!Director->ApplyPoseAtTime(
				Scenario.ReadProperty(TEXT("simulation/sim-time-sec")),
				Error))
			{
				return Fail(Error);
			}
			// A keyframed focal-length move has to reach the PIXELS, not
			// only the manifest, or the recorded intrinsics stop
			// describing the frames partway through the run.
			Capture->FOVAngle = static_cast<float>(FMath::RadiansToDegrees(
				2.0 * FMath::Atan(CameraSensorWidthMm /
				                  (2.0 * Director->GetAppliedFocalLengthMm()))));
		}

		// Component render-state updates are queued and flushed at end of
		// frame. A hand-driven loop has to flush them itself, or the capture
		// sees the scene from before the aircraft and its surfaces moved.
		World->SendAllEndOfFrameUpdates();
		FlushRenderingCommands();
		Capture->CaptureScene();
		FlushRenderingCommands();

		FTextureRenderTargetResource* Resource =
			RenderTarget->GameThread_GetRenderTargetResource();
		if (Resource == nullptr || !Resource->ReadPixels(Pixels) || Pixels.Num() == 0)
		{
			return Fail(TEXT("could not read the render target back"));
		}

		int32 Lit = 0;
		for (FColor& Pixel : Pixels)
		{
			Pixel.A = 255;
			if (Pixel.R > 24 || Pixel.G > 24 || Pixel.B > 24)
			{
				++Lit;
			}
		}
		// The blank-frame floor applies to the frames actually DELIVERED.
		// It used to see every rendered frame because every rendered
		// frame was written; now that the schedule gates writing, an
		// unwritten frame is nobody's frame. The floor itself is
		// unchanged and still absolute: one blank delivered frame fails
		// the run.
		if (Lit == 0)
		{
			++BlankFrames;
		}

		const FString FrameName = FString::Printf(
			TEXT("frame_%04d.png"),
			bConsumePoses ? NextCapture - 1 : Captured);
		TArray64<uint8> Png;
		FImageUtils::PNGCompressImageArray(Width, Height, Pixels, Png);
		if (!FFileHelper::SaveArrayToFile(Png, *FPaths::Combine(OutputDirectory, FrameName)))
		{
			return Fail(FString::Printf(TEXT("could not write %s"), *FrameName));
		}

		TSharedPtr<FJsonObject> Record = MakeShared<FJsonObject>();
		Record->SetStringField(TEXT("frame"), FrameName);
		// The digest of the bytes that went to disk: the Python side
		// hashes the file and must get this back (frame_integrity), and
		// Gate 10-R compares two renders' records directly.
		Record->SetStringField(TEXT("sha256"), RenderSha256Hex(Png.GetData(), Png.Num()));
		if (bDeterministic)
		{
			Record->SetBoolField(TEXT("deterministic_pins"), true);
		}
		Record->SetNumberField(TEXT("t"), Scenario.ReadProperty(TEXT("simulation/sim-time-sec")));
		Record->SetNumberField(TEXT("roll_deg"),
		                       Scenario.ReadProperty(TEXT("attitude/phi-rad")) * RenderRadiansToDegrees);
		Record->SetNumberField(TEXT("pitch_deg"),
		                       Scenario.ReadProperty(TEXT("attitude/theta-rad")) * RenderRadiansToDegrees);
		Record->SetNumberField(TEXT("aileron_cmd"), Scenario.Movement->Commands.Aileron);
		Record->SetNumberField(TEXT("camera_roll_deg"), Director->GetCameraRollDegrees());
		if (bLabels)
		{
			// Every label capture sees what the colour capture saw: the same
			// camera (attached to it) and the same lens, re-copied because a
			// keyframed focal move changes Capture->FOVAngle per frame.
			LabelDepthAll->FOVAngle = Capture->FOVAngle;
			LabelIdAll->FOVAngle = Capture->FOVAngle;
			FTextureRenderTargetResource* DepthResource =
				LabelDepthTarget->GameThread_GetRenderTargetResource();
			FTextureRenderTargetResource* IdResource =
				LabelIdTarget->GameThread_GetRenderTargetResource();
			const FReadSurfaceDataFlags RawFloats(RCM_MinMax, CubeFace_MAX);
			TArray<FLinearColor> DepthAll;
			TArray<FLinearColor> IdAll;
			LabelDepthAll->CaptureScene();
			FlushRenderingCommands();
			if (DepthResource == nullptr
			    || !DepthResource->ReadLinearColorPixels(DepthAll, RawFloats))
			{
				return Fail(TEXT("labels: could not read the scene depth back"));
			}
			LabelIdAll->CaptureScene();
			FlushRenderingCommands();
			if (IdResource == nullptr
			    || !IdResource->ReadLinearColorPixels(IdAll, RawFloats))
			{
				return Fail(TEXT("labels: could not read the ID pass back"));
			}
			const int32 Count = Width * Height;
			if (DepthAll.Num() != Count || IdAll.Num() != Count)
			{
				return Fail(FString::Printf(
					TEXT("labels: depth and ID readbacks are %d and %d pixels for a %dx%d frame"),
					DepthAll.Num(), IdAll.Num(), Width, Height));
			}
			TMap<int32, int32> ClassOfIntId;
			for (const FRenderLabelledObject& Entry : Labelled)
			{
				ClassOfIntId.Add(Entry.IntId, Entry.ClassId);
			}
			TArray<uint8> Mask;
			TArray<uint8> ClassMask;
			TArray<uint16> Depth16;
			TArray<float> DepthMetres;
			Mask.SetNumZeroed(Count);
			ClassMask.SetNumZeroed(Count);
			Depth16.SetNumZeroed(Count);
			DepthMetres.SetNumZeroed(Count);
			int32 UnlabelledGeometry = 0;
			int32 NonIntegerIds = 0;
			for (int32 i = 0; i < Count; ++i)
			{
				const float AllCm = DepthAll[i].R;
				const bool bAllGeometry = AllCm > 0.0f && AllCm < RenderLabelDepthSkyCm;
				// The stencil comes back as a float; an AA-free pass gives
				// whole numbers. A non-integer here is a measurement (a
				// blend or a resample), counted and reported, never hidden
				// by the rounding.
				const float IdValue = IdAll[i].R;
				const int32 IntId = FMath::Clamp(FMath::RoundToInt(IdValue), 0, 255);
				if (FMath::Abs(IdValue - static_cast<float>(IntId)) > 1.0e-3f)
				{
					++NonIntegerIds;
				}
				Mask[i] = static_cast<uint8>(IntId);
				if (IntId != 0)
				{
					const int32* ClassId = ClassOfIntId.Find(IntId);
					ClassMask[i] = ClassId != nullptr
						? static_cast<uint8>(FMath::Clamp(*ClassId, 0, 255)) : 0;
				}
				else if (bAllGeometry)
				{
					++UnlabelledGeometry;   // geometry with no stencil: id 0, class 0
				}
				DepthMetres[i] = bAllGeometry ? AllCm / 100.0f
				                              : std::numeric_limits<float>::infinity();
				const double Metres = bAllGeometry ? AllCm / 100.0
				                                   : RenderLabelDepthSaturationM;
				Depth16[i] = static_cast<uint16>(FMath::Clamp(
					FMath::RoundToInt(Metres / RenderLabelDepthScaleM), 0, 65535));
			}
			const FString Stem = FrameName.LeftChop(4);

			// Per object: pixels in the ID pass, the alone pass (aircraft
			// only), visible fraction, who occludes it, depth under its mask.
			TArray<TSharedPtr<FJsonValue>> ObjectRecords;
			int32 PrimarySilhouette = 0;
			int32 PrimaryVisible = 0;
			for (FRenderLabelledObject& Entry : Labelled)
			{
				int32 ObjectPixels = 0;
				TArray<float> Under;
				for (int32 i = 0; i < Count; ++i)
				{
					if (Mask[i] == Entry.IntId)
					{
						++ObjectPixels;
						if (FMath::IsFinite(DepthMetres[i]))
						{
							Under.Add(DepthMetres[i]);
						}
					}
				}
				TSharedPtr<FJsonObject> ObjectJson = MakeShared<FJsonObject>();
				ObjectJson->SetStringField(TEXT("id"), Entry.Id);
				ObjectJson->SetNumberField(TEXT("int_id"), Entry.IntId);
				ObjectJson->SetNumberField(TEXT("class_id"), Entry.ClassId);
				ObjectJson->SetNumberField(TEXT("pixels"), ObjectPixels);
				if (Entry.Alone != nullptr)
				{
					Entry.Alone->FOVAngle = Capture->FOVAngle;
					TArray<FLinearColor> IdAlone;
					Entry.Alone->CaptureScene();
					FlushRenderingCommands();
					if (!IdResource->ReadLinearColorPixels(IdAlone, RawFloats)
					    || IdAlone.Num() != Count)
					{
						return Fail(FString::Printf(
							TEXT("labels: could not read the alone pass of '%s' back"), *Entry.Id));
					}
					TArray<uint8> AloneMask;
					AloneMask.SetNumZeroed(Count);
					int32 PixelsAlone = 0;
					TSet<int32> Occluders;
					for (int32 i = 0; i < Count; ++i)
					{
						const int32 Value = FMath::Clamp(FMath::RoundToInt(IdAlone[i].R), 0, 255);
						if (Value == Entry.IntId)
						{
							AloneMask[i] = static_cast<uint8>(Value);
							++PixelsAlone;
							if (Mask[i] != 0 && Mask[i] != Entry.IntId)
							{
								Occluders.Add(static_cast<int32>(Mask[i]));
							}
						}
					}
					const FString AloneName = Stem + FString::Printf(TEXT("_alone_%d.png"), Entry.IntId);
					if (!RenderWriteGrayPng(FPaths::Combine(OutputDirectory, AloneName),
					                        AloneMask.GetData(), AloneMask.Num(), Width, Height, 8))
					{
						return Fail(FString::Printf(TEXT("labels: could not write %s"), *AloneName));
					}
					ObjectJson->SetNumberField(TEXT("pixels_alone"), PixelsAlone);
					ObjectJson->SetStringField(TEXT("alone_png"), AloneName);
					if (PixelsAlone > 0)
					{
						ObjectJson->SetNumberField(TEXT("visible_fraction"),
						                           static_cast<double>(ObjectPixels) / PixelsAlone);
					}
					else
					{
						ObjectJson->SetField(TEXT("visible_fraction"), MakeShared<FJsonValueNull>());
					}
					TArray<int32> OccluderIds = Occluders.Array();
					OccluderIds.Sort();
					TArray<TSharedPtr<FJsonValue>> OccludedBy;
					for (int32 Occluder : OccluderIds)
					{
						OccludedBy.Add(MakeShared<FJsonValueNumber>(Occluder));
					}
					ObjectJson->SetArrayField(TEXT("occluded_by"), OccludedBy);
					if (Entry.IntId == LabelPrimaryIntId)
					{
						PrimarySilhouette = PixelsAlone;
						PrimaryVisible = ObjectPixels;
					}
				}
				else
				{
					ObjectJson->SetField(TEXT("pixels_alone"), MakeShared<FJsonValueNull>());
					ObjectJson->SetField(TEXT("alone_png"), MakeShared<FJsonValueNull>());
					ObjectJson->SetField(TEXT("visible_fraction"), MakeShared<FJsonValueNull>());
					ObjectJson->SetArrayField(TEXT("occluded_by"), TArray<TSharedPtr<FJsonValue>>());
				}
				if (Under.Num() > 0)
				{
					Under.Sort();
					const int32 N = Under.Num();
					const double Median = (N % 2 == 1)
						? Under[N / 2]
						: 0.5 * (static_cast<double>(Under[N / 2 - 1]) + Under[N / 2]);
					ObjectJson->SetNumberField(TEXT("depth_min_m"), Under[0]);
					ObjectJson->SetNumberField(TEXT("depth_median_m"), Median);
				}
				else
				{
					ObjectJson->SetField(TEXT("depth_min_m"), MakeShared<FJsonValueNull>());
					ObjectJson->SetField(TEXT("depth_median_m"), MakeShared<FJsonValueNull>());
				}
				ObjectRecords.Add(MakeShared<FJsonValueObject>(ObjectJson));
			}

			const FString MaskName = Stem + TEXT("_mask.png");
			const FString ClassName = Stem + TEXT("_class.png");
			const FString DepthName = Stem + TEXT("_depth.png");
			const FString DepthF32Name = Stem + TEXT("_depth.f32");
			if (!RenderWriteGrayPng(FPaths::Combine(OutputDirectory, MaskName),
			                        Mask.GetData(), Mask.Num(), Width, Height, 8)
			    || !RenderWriteGrayPng(FPaths::Combine(OutputDirectory, ClassName),
			                           ClassMask.GetData(), ClassMask.Num(), Width, Height, 8)
			    || !RenderWriteGrayPng(FPaths::Combine(OutputDirectory, DepthName),
			                           Depth16.GetData(),
			                           static_cast<int64>(Depth16.Num()) * sizeof(uint16),
			                           Width, Height, 16))
			{
				return Fail(FString::Printf(TEXT("labels: could not write the label "
				                                 "files for %s"), *FrameName));
			}
			// The metric depth as raw little-endian float32, row-major,
			// width*height values, +inf for sky: no library on either side
			// (numpy.fromfile reads it), nothing lost to a 16-bit scale.
			TArray64<uint8> DepthBytes;
			DepthBytes.SetNumUninitialized(static_cast<int64>(Count) * sizeof(float));
			FMemory::Memcpy(DepthBytes.GetData(), DepthMetres.GetData(), DepthBytes.Num());
			if (!FFileHelper::SaveArrayToFile(DepthBytes, *FPaths::Combine(OutputDirectory, DepthF32Name)))
			{
				return Fail(FString::Printf(TEXT("labels: could not write %s"), *DepthF32Name));
			}
			// Declared per frame, ASCII only (gotcha 13): every Phase 10 key
			// is kept for its readers (the primary's silhouette/visible
			// counts now come from its alone pass and the ID pass), and the
			// new keys sit beside them.
			TSharedPtr<FJsonObject> Labels = MakeShared<FJsonObject>();
			Labels->SetStringField(TEXT("mask"), MaskName);
			Labels->SetStringField(TEXT("class_mask"), ClassName);
			Labels->SetStringField(TEXT("depth"), DepthName);
			Labels->SetNumberField(TEXT("depth_scale_m"), RenderLabelDepthScaleM);
			Labels->SetNumberField(TEXT("depth_saturation_m"), RenderLabelDepthSaturationM);
			Labels->SetNumberField(TEXT("silhouette_pixels"), PrimarySilhouette);
			Labels->SetNumberField(TEXT("visible_pixels"), PrimaryVisible);
			Labels->SetNumberField(TEXT("occlusion_fraction"),
			                       PrimarySilhouette > 0
			                           ? 1.0 - static_cast<double>(PrimaryVisible) / PrimarySilhouette
			                           : 0.0);
			FString Classes = TEXT("0 sky");
			if (Card.TaxonomyClasses.Num() > 0)
			{
				for (int32 i = 0; i < Card.TaxonomyClasses.Num(); ++i)
				{
					Classes += FString::Printf(TEXT(", %d %s"), i + 1, *Card.TaxonomyClasses[i]);
				}
			}
			else
			{
				Classes = TEXT("0 sky, 1 aircraft, 2 terrain or other");
			}
			Labels->SetStringField(TEXT("classes"), Classes);
			Labels->SetStringField(TEXT("method"),
			                       TEXT("custom-stencil ID pass, AA off; alone pass per aircraft"));
			Labels->SetStringField(TEXT("depth_f32"), DepthF32Name);
			Labels->SetStringField(TEXT("anti_aliasing"), TEXT("none"));
			Labels->SetStringField(TEXT("id_source"), LabelIdSource);
			Labels->SetNumberField(TEXT("unlabelled_geometry_pixels"), UnlabelledGeometry);
			Labels->SetNumberField(TEXT("non_integer_id_pixels"), NonIntegerIds);
			Labels->SetArrayField(TEXT("objects"), ObjectRecords);
			Record->SetObjectField(TEXT("labels"), Labels);
		}
		if (bLinear)
		{
			LinearCapture->FOVAngle = Capture->FOVAngle;
			LinearCapture->CaptureScene();
			FlushRenderingCommands();
			FTextureRenderTargetResource* LinearResource =
				LinearTarget->GameThread_GetRenderTargetResource();
			TArray<FLinearColor> Linear;
			if (LinearResource == nullptr
			    || !LinearResource->ReadLinearColorPixels(
			           Linear, FReadSurfaceDataFlags(RCM_MinMax, CubeFace_MAX)))
			{
				return Fail(TEXT("linear: could not read the HDR capture back"));
			}
			IImageWrapperModule& Wrappers =
				FModuleManager::LoadModuleChecked<IImageWrapperModule>(TEXT("ImageWrapper"));
			TSharedPtr<IImageWrapper> Exr = Wrappers.CreateImageWrapper(EImageFormat::EXR);
			const FString LinearName = FrameName.LeftChop(4) + TEXT("_linear.exr");
			if (!Exr.IsValid()
			    || !Exr->SetRaw(Linear.GetData(),
			                    static_cast<int64>(Linear.Num()) * sizeof(FLinearColor),
			                    Width, Height, ERGBFormat::RGBAF, 32))
			{
				return Fail(TEXT("linear: could not encode the EXR"));
			}
			const TArray64<uint8> ExrBytes = Exr->GetCompressed();
			if (ExrBytes.Num() == 0
			    || !FFileHelper::SaveArrayToFile(ExrBytes, *FPaths::Combine(OutputDirectory, LinearName)))
			{
				return Fail(FString::Printf(TEXT("linear: could not write %s"), *LinearName));
			}
			Record->SetStringField(TEXT("linear"), LinearName);
		}
		if (bConsumePoses)
		{
			// Additive Camera Phase 1 fields (ASCII only -- gotcha 13; the
			// camera's id string stays in the Python-written manifest): the
			// pose ACTUALLY APPLIED, expressed back in the card's own local
			// frame so the Python verifier grades applied-vs-solved without
			// knowing engine units. The inverse of the placement mapping
			// above: EngineToProjected, then true heading = engine yaw + 90.
			FVector AppliedProjected;
			Scenario.GeoReferencing->EngineToProjected(
				Director->GetActorLocation(), AppliedProjected);
			const FRotator AppliedRotation = Director->GetActorRotation();
			Record->SetNumberField(TEXT("camera_index"),
			                       static_cast<double>(ConsumedCameraIndex));
			Record->SetNumberField(TEXT("camera_applied_north_m"),
			                       AppliedProjected.Y - CameraOriginYMetres);
			Record->SetNumberField(TEXT("camera_applied_east_m"),
			                       AppliedProjected.X - CameraOriginXMetres);
			Record->SetNumberField(TEXT("camera_applied_alt_m"),
			                       AppliedProjected.Z);
			Record->SetNumberField(TEXT("camera_applied_yaw_deg"),
			                       FMath::Fmod(AppliedRotation.Yaw + 90.0 + 360.0, 360.0));
			Record->SetNumberField(TEXT("camera_applied_pitch_deg"),
			                       AppliedRotation.Pitch);
			Record->SetNumberField(TEXT("camera_applied_roll_deg"),
			                       AppliedRotation.Roll);
		}
		Record->SetNumberField(TEXT("lit_pixels"), Lit);
		// Load factor and the wind actually inside the FDM this frame -- the
		// null tests (turbulence reached the FDM; the ridge's wind reached
		// the FDM) read these, not the scene.
		Record->SetNumberField(TEXT("n_z"),
		                       Scenario.ReadProperty(TEXT("accelerations/Nz")));
		Record->SetNumberField(TEXT("wind_down_fps"),
		                       Scenario.ReadProperty(TEXT("atmosphere/wind-down-fps")));
		// Phase 7 evidence channels: the turbulence realisation the FDM
		// integrated and the W20 the intensity coupling wrote.
		Record->SetNumberField(TEXT("turb_down_fps"),
		                       Scenario.ReadProperty(TEXT("atmosphere/turb-down-fps")));
		Record->SetNumberField(TEXT("w20_fps"),
		                       Scenario.ReadProperty(
		                           TEXT("atmosphere/turbulence/milspec/windspeed_at_20ft_AGL-fps")));
		// The flight-state channels the telemetry panel draws: what the FDM
		// actually did, per frame, to stand next to what the spec commanded.
		// Read from the FDM like everything else here -- never derived from
		// the scene.
		Record->SetNumberField(TEXT("altitude_m"),
		                       Scenario.ReadProperty(TEXT("position/h-sl-meters")));
		Record->SetNumberField(TEXT("cas_kt"),
		                       Scenario.ReadProperty(TEXT("velocities/vc-kts")));
		Record->SetNumberField(TEXT("tas_kt"),
		                       Scenario.ReadProperty(TEXT("velocities/vtrue-kts")));
		Record->SetNumberField(TEXT("heading_deg"),
		                       Scenario.ReadProperty(TEXT("attitude/psi-rad")) * RenderRadiansToDegrees);
		Record->SetNumberField(TEXT("agl_m"),
		                       Scenario.ReadProperty(TEXT("position/h-agl-ft")) * 0.3048);
		Record->SetNumberField(TEXT("wind_north_fps"),
		                       Scenario.ReadProperty(TEXT("atmosphere/wind-north-fps")));
		Record->SetNumberField(TEXT("wind_east_fps"),
		                       Scenario.ReadProperty(TEXT("atmosphere/wind-east-fps")));

		// What the animator actually applied to geometry, read back off the
		// bindings rather than recomputed -- so a binding that computed a
		// deflection and moved nothing shows up as a surface that never moved.
		TSharedPtr<FJsonObject> Surfaces = MakeShared<FJsonObject>();
		for (const FFlightSimSurfaceBinding& Binding : Animator->Bindings)
		{
			if (Binding.TargetComponent == nullptr)
			{
				continue;
			}
			// Measured off the scene component, as the angle it has actually
			// been rotated away from its neutral pose -- not recomputed from
			// the property. A binding that read a deflection and moved nothing
			// therefore reports zero here, which is the failure worth catching.
			const FQuat Applied =
				Binding.NeutralRotation.Quaternion().Inverse() *
				Binding.TargetComponent->GetRelativeRotation().Quaternion();
			FVector Axis;
			float Angle = 0.0f;
			Applied.ToAxisAndAngle(Axis, Angle);
			const double Sign =
				FMath::Sign(Axis | Binding.RotationAxis.GetSafeNormal());
			Surfaces->SetNumberField(Binding.BoneName.ToString(),
			                         FMath::RadiansToDegrees(Angle) * Sign);
		}
		Record->SetObjectField(TEXT("surface_component_deg"), Surfaces);

		// Landmarks, projected through the camera of record, so the harness
		// samples known world points instead of guessing regions by eye. The
		// aircraft ground point is its position dropped to the visual ground.
		// Camera Phase 2: the card's own landmarks, projected through THIS
		// capture's transform and field of view, so the Python verifier can
		// grade its projection against the engine's. Written whenever the
		// card carried landmarks, independently of the Gate 6 visual set
		// below.
		if (LandmarkNames.Num() > 0)
		{
			TSharedPtr<FJsonObject> Landmarks = MakeShared<FJsonObject>();
			for (int32 i = 0; i < LandmarkNames.Num(); ++i)
			{
				FVector EngineLocation;
				Scenario.GeoReferencing->ProjectedToEngine(
					LandmarkProjectedMetres[i], EngineLocation);
				FVector2D Pixel;
				const bool bVisible = ProjectToPixel(Capture, Width, Height,
				                                     EngineLocation, Pixel);
				TSharedPtr<FJsonObject> Entry = MakeShared<FJsonObject>();
				Entry->SetBoolField(TEXT("visible"), bVisible);
				Entry->SetNumberField(TEXT("px"), Pixel.X);
				Entry->SetNumberField(TEXT("py"), Pixel.Y);
				Landmarks->SetObjectField(LandmarkNames[i], Entry);
			}
			Record->SetObjectField(TEXT("landmarks"), Landmarks);
		}
		if (bConsumePoses)
		{
			// The intrinsics ACTUALLY applied, on EVERY consume-poses frame
			// (contracts §1; they used to ride only when the card carried
			// landmarks), so the verifier projects without guessing and a
			// disagreement with the manifest is visible rather than assumed
			// away.
			Record->SetNumberField(TEXT("applied_focal_length_mm"),
			                       Director->GetAppliedFocalLengthMm());
			Record->SetNumberField(TEXT("applied_sensor_width_mm"),
			                       CameraSensorWidthMm);
			Record->SetNumberField(TEXT("applied_fov_deg"),
			                       Capture->FOVAngle);
			Record->SetNumberField(TEXT("applied_width_px"), Width);
			Record->SetNumberField(TEXT("applied_height_px"), Height);
		}

		if (bVisual)
		{
			// ADD to the card's landmarks; do not replace them. These four
			// are Gate 6's scene features and the card's are the camera
			// phase's reference set, and both have always been written to
			// one field name -- so this block silently overwrote however
			// many the card carried with exactly four. The block above says
			// it writes "independently of the Gate 6 visual set below",
			// which was true of the writing and not of the result.
			//
			// It cost nothing while nothing rendered with -Visual, and
			// everything the moment something did: 36 landmarks became 4,
			// none of them named in the manifest, and both engine-referenced
			// checks -- the two this phase exists for -- went from PASS to
			// NOT RUN inside a summary that still said PASSED. The two name
			// sets are disjoint (air_*/ground_*/terrain_* against
			// near_peak/far_peak/valley/aircraft_ground), so they merge.
			const TSharedPtr<FJsonObject>* Existing = nullptr;
			TSharedPtr<FJsonObject> Landmarks =
				Record->TryGetObjectField(TEXT("landmarks"), Existing)
					? *Existing : MakeShared<FJsonObject>();
			auto AddLandmark = [&](const TCHAR* LandmarkName, const FVector& WorldCm)
			{
				FVector2D Pixel;
				const bool bVisible =
					ProjectToPixel(Capture, Width, Height, WorldCm, Pixel);
				TSharedPtr<FJsonObject> Entry = MakeShared<FJsonObject>();
				Entry->SetBoolField(TEXT("visible"), bVisible);
				Entry->SetNumberField(TEXT("px"), Pixel.X);
				Entry->SetNumberField(TEXT("py"), Pixel.Y);
				Landmarks->SetObjectField(LandmarkName, Entry);
			};
			AddLandmark(TEXT("near_peak"), VisualScene.NearPeakWorldCm);
			AddLandmark(TEXT("far_peak"), VisualScene.FarPeakWorldCm);
			// The plain between aircraft and ridge, where the terrain shot's
			// shadow band falls.
			AddLandmark(TEXT("valley"),
			            FVector(VisualScene.NearPeakWorldCm.X, -520000.0, 0.0));
			const FVector AircraftLocation = Scenario.Aircraft->GetActorLocation();
			AddLandmark(TEXT("aircraft_ground"),
			            FVector(AircraftLocation.X, AircraftLocation.Y, 0.0));
			Record->SetObjectField(TEXT("landmarks"), Landmarks);
		}
		FrameRecords.Add(MakeShared<FJsonValueObject>(Record));
		++Captured;
	}

	if (bConsumePoses && NextCapture != CaptureTimes.Num())
	{
		return Fail(FString::Printf(
			TEXT("consume-poses: emitted %d of the %d scheduled images; "
			     "the run ended before the schedule did, so the manifest "
			     "would name frames that do not exist"),
			NextCapture, CaptureTimes.Num()));
	}
	if (Captured == 0)
	{
		return Fail(TEXT("no frames were captured"));
	}
	if (BlankFrames > 0)
	{
		return Fail(FString::Printf(
			TEXT("%d of %d frames contain nothing above the background. A file "
			     "that exists is not a frame that shows something."),
			BlankFrames, Captured));
	}

	TSharedPtr<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("host"), TEXT("unreal"));
	Root->SetStringField(TEXT("spec_digest"), Card.SpecDigest);
	if (MeshAirframe.bLoaded)
	{
		Root->SetStringField(TEXT("airframe"),
		                     FString::Printf(TEXT("%s (FDM %s)"),
		                                     *MeshAirframe.MeshAirframe,
		                                     *MeshAirframe.FdmName));
		TSharedPtr<FJsonObject> Mesh = MakeShared<FJsonObject>();
		Mesh->SetStringField(TEXT("name"), MeshAirframe.Name);
		Mesh->SetStringField(TEXT("mesh_airframe"), MeshAirframe.MeshAirframe);
		Mesh->SetStringField(TEXT("fdm"), MeshAirframe.FdmName);
		Mesh->SetStringField(TEXT("license"), MeshAirframe.License);
		Mesh->SetStringField(TEXT("repo"), MeshAirframe.Repo);
		Mesh->SetStringField(TEXT("commit"), MeshAirframe.Commit);
		Root->SetObjectField(TEXT("mesh"), Mesh);
	}
	else
	{
		Root->SetStringField(TEXT("airframe"), TEXT("placeholder boxes, not a visual asset"));
	}
	// Camera Phase 2 (package A): what was DRAWN and where within the
	// actor, so verify's drawn_airframe check grades the frames against
	// the mesh the manifest expected without inferring it from other keys.
	// A mesh from a version-1 manifest reports its origin as the zero it
	// was actually attached at, and the version that caused it.
	{
		TSharedPtr<FJsonObject> Drawn = MakeShared<FJsonObject>();
		if (MeshAirframe.bLoaded)
		{
			Drawn->SetStringField(TEXT("kind"), TEXT("mesh"));
			TArray<TSharedPtr<FJsonValue>> Origin;
			Origin.Add(MakeShared<FJsonValueNumber>(MeshAirframe.MeshOriginActorCm.X));
			Origin.Add(MakeShared<FJsonValueNumber>(MeshAirframe.MeshOriginActorCm.Y));
			Origin.Add(MakeShared<FJsonValueNumber>(MeshAirframe.MeshOriginActorCm.Z));
			Drawn->SetArrayField(TEXT("mesh_origin_actor_cm"), Origin);
			Drawn->SetNumberField(TEXT("manifest_version"), MeshAirframe.ManifestVersion);
			Drawn->SetStringField(TEXT("origin_basis"), MeshAirframe.OriginBasis);
			Drawn->SetNumberField(TEXT("triangles"), MeshAirframe.Triangles);
		}
		else
		{
			Drawn->SetStringField(TEXT("kind"), TEXT("placeholder"));
			Drawn->SetField(TEXT("mesh_origin_actor_cm"), MakeShared<FJsonValueNull>());
			Drawn->SetField(TEXT("manifest_version"), MakeShared<FJsonValueNull>());
			Drawn->SetStringField(TEXT("origin_basis"),
			                      TEXT("placeholder boxes about the actor origin (structural datum)"));
		}
		Root->SetObjectField(TEXT("drawn"), Drawn);
	}
	// Phase 2 (packages B + C): the labelled objects this pass wrote ids
	// for (the card's list, or the default pair), and each traffic mesh
	// drawn, so a reader of render.json alone resolves every integer in
	// the ID image and knows which meshes the traffic actors carried.
	if (bLabels)
	{
		TArray<TSharedPtr<FJsonValue>> ObjectList;
		for (const FRenderLabelledObject& Entry : Labelled)
		{
			TSharedPtr<FJsonObject> ObjectJson = MakeShared<FJsonObject>();
			ObjectJson->SetStringField(TEXT("id"), Entry.Id);
			ObjectJson->SetNumberField(TEXT("int_id"), Entry.IntId);
			ObjectJson->SetStringField(TEXT("class"), Entry.Class);
			ObjectJson->SetNumberField(TEXT("class_id"), Entry.ClassId);
			ObjectJson->SetStringField(TEXT("role"), Entry.Role);
			ObjectJson->SetBoolField(TEXT("alone_pass"), Entry.Alone != nullptr);
			ObjectList.Add(MakeShared<FJsonValueObject>(ObjectJson));
		}
		Root->SetArrayField(TEXT("objects"), ObjectList);
		Root->SetStringField(TEXT("labels_id_source"), LabelIdSource);
	}
	if (TrafficMeshes.Num() > 0)
	{
		TArray<TSharedPtr<FJsonValue>> TrafficList;
		for (int32 Index = 0; Index < TrafficMeshes.Num(); ++Index)
		{
			TSharedPtr<FJsonObject> Entry = MakeShared<FJsonObject>();
			Entry->SetStringField(TEXT("id"), Card.Traffic[Index].Id);
			Entry->SetNumberField(TEXT("int_id"), Card.Traffic[Index].IntId);
			Entry->SetStringField(TEXT("mesh_airframe"), TrafficMeshes[Index].MeshAirframe);
			Entry->SetStringField(TEXT("fdm"), TrafficMeshes[Index].FdmName);
			Entry->SetStringField(TEXT("license"), TrafficMeshes[Index].License);
			Entry->SetNumberField(TEXT("manifest_version"), TrafficMeshes[Index].ManifestVersion);
			Entry->SetStringField(TEXT("origin_basis"), TrafficMeshes[Index].OriginBasis);
			Entry->SetStringField(TEXT("track"), Card.Traffic[Index].Track);
			Entry->SetNumberField(TEXT("range_m"), Card.Traffic[Index].RangeMetres);
			TrafficList.Add(MakeShared<FJsonValueObject>(Entry));
		}
		Root->SetArrayField(TEXT("traffic"), TrafficList);
	}
	Root->SetNumberField(TEXT("width"), Width);
	Root->SetNumberField(TEXT("height"), Height);
	Root->SetNumberField(TEXT("frames"), Captured);
	Root->SetNumberField(TEXT("bound_surfaces"), Animator->GetBoundSurfaceCount());
	// Peaks over the bindings that are attached to geometry only. Including the
	// unattached ones would report the gear binding's 90 degrees, which nothing
	// on screen ever did.
	TSharedPtr<FJsonObject> Peaks = MakeShared<FJsonObject>();
	for (const FFlightSimSurfaceBinding& Binding : Animator->Bindings)
	{
		if (Binding.TargetComponent != nullptr)
		{
			Peaks->SetNumberField(Binding.BoneName.ToString(),
			                      Binding.PeakDeflectionDegrees);
		}
	}
	Root->SetObjectField(TEXT("surface_peak_deg"), Peaks);
	// The preset word this pass ran with -- the same value as
	// scene.camera_preset below (contracts §1: the root key was a
	// hard-coded "LaggedChase" on every pass, wingman and tower included).
	// In a consume-poses pass the word is inert and camera_consume_poses
	// beside it says so: the camera flew the card's solved track.
	Root->SetStringField(TEXT("camera_preset"), CameraPreset);
	Root->SetBoolField(TEXT("camera_keeps_horizon_level"), Director->PresetKeepsHorizonLevel());
	// Camera Phase 1, additive: which solved camera this pass consumed
	// (numbers only -- gotcha 13; camera id strings live in the
	// Python-written capture manifest).
	Root->SetBoolField(TEXT("camera_consume_poses"), bConsumePoses);
	if (bConsumePoses)
	{
		Root->SetNumberField(TEXT("camera_index"),
		                     static_cast<double>(ConsumedCameraIndex));
	}
	// -- Phase 2 (contracts §1, §10): render_settings -- every rendering
	// console variable this pass set or relies on, READ BACK by its r.
	// name (the value found, or "absent"), the anti-aliasing method per
	// capture as the capture's own show flags say, the exposure mode and
	// EV100, the RHI, and the preset offsets as flown. Nothing here is
	// what the ini asked for; it is what the engine reported.
	{
		TSharedPtr<FJsonObject> RenderSettings = MakeShared<FJsonObject>();
		auto ConsoleString = [](const TCHAR* Name) -> FString
		{
			IConsoleVariable* Variable = IConsoleManager::Get().FindConsoleVariable(Name);
			return Variable != nullptr ? Variable->GetString() : FString(TEXT("absent"));
		};
		TSharedPtr<FJsonObject> Console = MakeShared<FJsonObject>();
		const TCHAR* const ConsoleNames[] = {
			TEXT("r.AntiAliasingMethod"),
			TEXT("r.DynamicGlobalIlluminationMethod"),
			TEXT("r.ReflectionMethod"),
			TEXT("r.Lumen.HardwareRayTracing"),
			TEXT("r.GenerateMeshDistanceFields"),
			TEXT("r.Shadow.Virtual.Enable"),
			TEXT("r.Nanite.ProjectEnabled"),
			TEXT("r.Nanite"),
			TEXT("r.CustomDepth"),
			TEXT("r.ScreenPercentage"),
			TEXT("r.DefaultFeature.AutoExposure.ExtendDefaultLuminanceRange"),
			TEXT("r.Substrate"),
			TEXT("r.TextureStreaming"),
			TEXT("r.Streaming.FullyLoadUsedTextures"),
			TEXT("r.ForceLOD"),
		};
		for (const TCHAR* Name : ConsoleNames)
		{
			Console->SetStringField(Name, ConsoleString(Name));
		}
		RenderSettings->SetObjectField(TEXT("console"), Console);

		auto AntiAliasingName = [&](bool bShowFlag) -> FString
		{
			if (!bShowFlag)
			{
				return TEXT("none");
			}
			IConsoleVariable* Variable =
				IConsoleManager::Get().FindConsoleVariable(TEXT("r.AntiAliasingMethod"));
			if (Variable == nullptr)
			{
				return TEXT("absent (show flag on, r.AntiAliasingMethod not found)");
			}
			switch (Variable->GetInt())
			{
			case 0: return TEXT("none");
			case 1: return TEXT("FXAA");
			case 2: return TEXT("TAA");
			case 3: return TEXT("MSAA");
			case 4: return TEXT("TSR");
			default: return FString::Printf(TEXT("unknown(%d)"), Variable->GetInt());
			}
		};
		TSharedPtr<FJsonObject> AntiAliasing = MakeShared<FJsonObject>();
		AntiAliasing->SetStringField(TEXT("beauty"),
			AntiAliasingName(Capture->ShowFlags.AntiAliasing != 0));
		if (LinearCapture != nullptr)
		{
			AntiAliasing->SetStringField(TEXT("linear"),
				AntiAliasingName(LinearCapture->ShowFlags.AntiAliasing != 0));
		}
		if (LabelDepthAll != nullptr)
		{
			// Measured from the capture, not asserted: a label pass whose
			// show flag is on is a defect the verifier should see by name.
			AntiAliasing->SetStringField(TEXT("labels"),
				LabelDepthAll->ShowFlags.AntiAliasing != 0
					? TEXT("DEFECT: label capture anti-aliasing show flag is on")
					: TEXT("none"));
		}
		RenderSettings->SetObjectField(TEXT("anti_aliasing"), AntiAliasing);

		TSharedPtr<FJsonObject> BeautyFlags = MakeShared<FJsonObject>();
		BeautyFlags->SetBoolField(TEXT("anti_aliasing"), Capture->ShowFlags.AntiAliasing != 0);
		BeautyFlags->SetBoolField(TEXT("temporal_aa"), Capture->ShowFlags.TemporalAA != 0);
		BeautyFlags->SetBoolField(TEXT("motion_blur"), Capture->ShowFlags.MotionBlur != 0);
		BeautyFlags->SetBoolField(TEXT("bloom"), Capture->ShowFlags.Bloom != 0);
		BeautyFlags->SetBoolField(TEXT("fog"), Capture->ShowFlags.Fog != 0);
		BeautyFlags->SetBoolField(TEXT("atmosphere"), Capture->ShowFlags.Atmosphere != 0);
		BeautyFlags->SetBoolField(TEXT("volumetric_fog"), Capture->ShowFlags.VolumetricFog != 0);
		BeautyFlags->SetBoolField(TEXT("cloud"), Capture->ShowFlags.Cloud != 0);
		BeautyFlags->SetBoolField(TEXT("depth_of_field"), Capture->ShowFlags.DepthOfField != 0);
		BeautyFlags->SetBoolField(TEXT("lens_flares"), Capture->ShowFlags.LensFlares != 0);
		BeautyFlags->SetBoolField(TEXT("dynamic_shadows"), Capture->ShowFlags.DynamicShadows != 0);
		RenderSettings->SetObjectField(TEXT("beauty_show_flags"), BeautyFlags);

		// Scene captures render at their target's size; the screen
		// percentage CVar is recorded above as found, the size here.
		TArray<TSharedPtr<FJsonValue>> CaptureSize;
		CaptureSize.Add(MakeShared<FJsonValueNumber>(Width));
		CaptureSize.Add(MakeShared<FJsonValueNumber>(Height));
		RenderSettings->SetArrayField(TEXT("capture_size_px"), CaptureSize);
		RenderSettings->SetStringField(TEXT("screen_percentage"),
			TEXT("captures render at capture_size_px; r.ScreenPercentage recorded in console"));

		RenderSettings->SetStringField(TEXT("exposure_mode"), ExposureMode);
		RenderSettings->SetStringField(TEXT("exposure_source"), ExposureSource);
		if (bAppliedEv100)
		{
			RenderSettings->SetNumberField(TEXT("ev100"), AppliedEv100);
		}
		else
		{
			RenderSettings->SetField(TEXT("ev100"), MakeShared<FJsonValueNull>());
		}
		RenderSettings->SetNumberField(TEXT("exposure_bias"), ExposureBias);
		RenderSettings->SetStringField(TEXT("extend_default_luminance_range"),
			ConsoleString(TEXT("r.DefaultFeature.AutoExposure.ExtendDefaultLuminanceRange")));
		RenderSettings->SetStringField(TEXT("rhi"), GDynamicRHI->GetName());
		RenderSettings->SetStringField(TEXT("shader_platform"),
			LexToString(GMaxRHIShaderPlatform));
		RenderSettings->SetBoolField(TEXT("deterministic_pins"), bDeterministic);

		auto OffsetArray = [](const FVector& Offset)
		{
			TArray<TSharedPtr<FJsonValue>> Out;
			Out.Add(MakeShared<FJsonValueNumber>(Offset.X));
			Out.Add(MakeShared<FJsonValueNumber>(Offset.Y));
			Out.Add(MakeShared<FJsonValueNumber>(Offset.Z));
			return Out;
		};
		RenderSettings->SetArrayField(TEXT("cockpit_offset_m"),
		                              OffsetArray(Director->ShoulderOffsetMetres));
		RenderSettings->SetArrayField(TEXT("chase_offset_m"),
		                              OffsetArray(Director->ChaseOffsetMetres));
		RenderSettings->SetArrayField(TEXT("wingman_offset_m"),
		                              OffsetArray(Director->WingmanOffsetMetres));
		RenderSettings->SetStringField(TEXT("preset_offset_rule"),
			TEXT("Python's (core/scenario/camera.py FALLBACK_CHASE_OFFSET, WINGMAN_OFFSET, "
			     "SHOULDER_OFFSET): body offsets from the CG, unscaled; chase as flown "
			     "is the shot constant or -chase="));
		Root->SetObjectField(TEXT("render_settings"), RenderSettings);
	}
	// -- Phase 2 (contracts §5.4): look_applied -- every weather/sky
	// parameter the scene actually applied, from the scene's own record.
	if (bVisual && VisualScene.LookApplied.IsValid())
	{
		TSharedPtr<FJsonObject> Look = VisualScene.LookApplied;
		Look->SetStringField(TEXT("source"), LookSource);
		if (bLookAerosol && Look->HasTypedField<EJson::Object>(TEXT("aerosol")))
		{
			Look->GetObjectField(TEXT("aerosol"))->SetNumberField(TEXT("card_aerosol"), LookAerosol);
		}
		TArray<TSharedPtr<FJsonValue>> Overrides;
		for (const FString& Name : LookProbeOverrides)
		{
			Overrides.Add(MakeShared<FJsonValueString>(Name));
		}
		Look->SetArrayField(TEXT("probe_overrides"), Overrides);
		TSharedPtr<FJsonObject> ExposureRecord = MakeShared<FJsonObject>();
		ExposureRecord->SetStringField(TEXT("mode"), ExposureMode);
		ExposureRecord->SetStringField(TEXT("source"), ExposureSource);
		if (bAppliedEv100)
		{
			ExposureRecord->SetNumberField(TEXT("ev100"), AppliedEv100);
		}
		else
		{
			ExposureRecord->SetField(TEXT("ev100"), MakeShared<FJsonValueNull>());
		}
		Look->SetObjectField(TEXT("exposure"), ExposureRecord);
		Root->SetObjectField(TEXT("look_applied"), Look);
	}
	TSharedPtr<FJsonObject> Scene = MakeShared<FJsonObject>();
	Scene->SetBoolField(TEXT("visual"), bVisual);
	Scene->SetStringField(TEXT("shot"), Shot);
	Scene->SetBoolField(TEXT("dynamic_shadows"), !bNoShadows);
	Scene->SetBoolField(TEXT("aircraft_hidden"), bHideAircraft);
	Scene->SetStringField(TEXT("exposure"), (bVisual && !bAutoExposure)
		? (bAppliedEv100
			? *FString::Printf(TEXT("manual, EV100 %.2f (physical camera)"), AppliedEv100)
			: *FString::Printf(TEXT("manual, AutoExposureBias %.1f"), ExposureBias))
		: TEXT("auto (default metering)"));
	if (bVisual && !TerrainPath.IsEmpty())
	{
		Scene->SetStringField(TEXT("terrain_sha256"), VisualScene.TerrainSha256);
		Scene->SetNumberField(TEXT("terrain_peak_m"), VisualScene.TerrainPeakMetres);
		Scene->SetBoolField(TEXT("terrain_georeferenced"), bGeorefTerrain);
		if (bGeorefTerrain)
		{
			Scene->SetStringField(TEXT("terrain_crs"), VisualScene.TerrainCrs);
			Scene->SetStringField(TEXT("terrain_name"), VisualScene.TerrainName);
			// Phase 2 (contracts §10): the posting the tiled terrain ACHIEVED
			// (raster pixel size x the stride the triangle budget admitted).
			Scene->SetNumberField(TEXT("terrain_posting_m"), VisualScene.TerrainPostingMetres);
			Scene->SetNumberField(TEXT("terrain_stride"), VisualScene.TerrainStride);
			Scene->SetNumberField(TEXT("terrain_tiles"), VisualScene.TerrainTiles);
			Scene->SetNumberField(TEXT("terrain_triangles"), VisualScene.TerrainTriangles);
			if (!VisualScene.ImagerySha256.IsEmpty())
			{
				Scene->SetStringField(TEXT("terrain_material"),
					TEXT("true-colour satellite imagery drape (see imagery_* "
					     "fields; acquisition-date and resolution limits in "
					     "VALIDITY.md)"));
				Scene->SetStringField(TEXT("imagery_dataset"), VisualScene.ImageryDataset);
				Scene->SetStringField(TEXT("imagery_file"), VisualScene.ImageryFile);
				Scene->SetStringField(TEXT("imagery_sha256"), VisualScene.ImagerySha256);
				Scene->SetStringField(TEXT("imagery_license"), VisualScene.ImageryLicense);
				Scene->SetStringField(TEXT("imagery_attribution"), VisualScene.ImageryAttribution);
			}
			else
			{
				Scene->SetStringField(TEXT("terrain_material"),
					TEXT("slope/altitude classified vertex colours (approximated)"));
			}
			// Honesty label carried per clip: the mountains on screen are the
			// real raster, the ground the GEAR model feels is still the
			// spec's flat slab. Wind coupling is separate and stated below.
			Scene->SetStringField(TEXT("physics_ground"),
				TEXT("flat slab at spec terrain_elevation; visual terrain "
				     "carries no collision"));
		}
	}
	if (MeshAirframe.bLoaded)
	{
		Scene->SetStringField(TEXT("livery"), MeshAirframe.Livery);
	}
	if (bVisual)
	{
		Scene->SetNumberField(TEXT("fog_density"), FogDensity);
		if (bSunOverride)
		{
			Scene->SetNumberField(TEXT("sun_elevation_deg"), SunElevationDeg);
			Scene->SetNumberField(TEXT("sun_azimuth_deg"), SunAzimuthDeg);
		}
		Scene->SetBoolField(TEXT("sun_animated"), bSunAnimated);
		if (bSunAnimated)
		{
			Scene->SetNumberField(TEXT("sun_elevation_end_deg"), SunElevationEndDeg);
			Scene->SetNumberField(TEXT("sun_azimuth_end_deg"), SunAzimuthEndDeg);
		}
	}
	Scene->SetStringField(TEXT("camera_preset"), CameraPreset);
	Scene->SetBoolField(TEXT("camera_inherits_roll"),
	                    !Director->PresetKeepsHorizonLevel());
	Root->SetObjectField(TEXT("scene"), Scene);

	// Environmental couplings, stated per run rather than assumed.
	TSharedPtr<FJsonObject> Environment = MakeShared<FJsonObject>();
	Environment->SetStringField(TEXT("turbulence"), Card.Turbulence);
	if (Card.Turbulence != TEXT("none"))
	{
		Environment->SetNumberField(TEXT("turbulence_seed"),
		                            static_cast<double>(Card.TurbulenceSeed));
		Environment->SetStringField(TEXT("turbulence_parity"),
			TEXT("visual/telemetry run; host parity for turbulence is decided "
			     "by the harness, not assumed here"));
	}
	Environment->SetNumberField(TEXT("wind_speed_kt"), Card.WindSpeedKnots);
	Environment->SetNumberField(TEXT("wind_from_deg"), Card.WindFromDegrees);
	Environment->SetBoolField(TEXT("wind_schedule"),
	                          Card.WindScheduleTimes.Num() > 0);
	Environment->SetBoolField(TEXT("orographic"), Card.bOrographic);
	if (bNoOrographic)
	{
		Environment->SetStringField(TEXT("orographic_note"),
			TEXT("null-test control: card's orographic coupling severed by "
			     "-NoOrographic"));
	}
	if (OrographicSelftest.Num() > 0)
	{
		Environment->SetArrayField(TEXT("orographic_selftest"), OrographicSelftest);
	}
	Environment->SetBoolField(TEXT("downburst"), Card.bDownburst);
	if (Card.bDownburst)
	{
		Environment->SetStringField(TEXT("downburst_delivery"),
			TEXT("position-coupled: field evaluated at the aircraft's actual "
			     "position each step (the nominal-track label is obsolete for "
			     "this clip)"));
		Environment->SetNumberField(TEXT("downburst_core_radius_m"),
		                            Card.DownburstCoreRadiusMetres);
		Environment->SetNumberField(TEXT("downburst_outflow_max_mps"),
		                            Card.DownburstOutflowMaxMps);
		Environment->SetNumberField(TEXT("downburst_outflow_height_m"),
		                            Card.DownburstOutflowHeightMetres);
		Environment->SetArrayField(TEXT("downburst_selftest"), DownburstSelftest);
	}
	Environment->SetBoolField(TEXT("rotor"), Card.bRotor);
	if (Card.bRotor)
	{
		Environment->SetStringField(TEXT("rotor_delivery"),
			TEXT("per-step W20 from the lee-sink field; seed and pinned "
			     "severity written once (JSBSIM_CORRECTIONS section 13); coupling "
			     "valid below 300 m AGL"));
		Environment->SetArrayField(TEXT("rotor_selftest"), RotorSelftest);
	}
	Environment->SetBoolField(TEXT("log_profile"), Card.bLogProfile);
	if (Card.bLogProfile)
	{
		Environment->SetArrayField(TEXT("log_profile_selftest"), LogProfileSelftest);
	}
	Environment->SetBoolField(TEXT("thermals"), Card.bThermals);
	if (Card.bThermals)
	{
		Environment->SetNumberField(TEXT("thermals_count"),
		                            Card.ThermalNorthMetres.Num());
		Environment->SetArrayField(TEXT("thermals_selftest"), ThermalsSelftest);
	}
	Environment->SetBoolField(TEXT("turbulence_schedule"),
	                          Card.TurbulenceScheduleTimes.Num() > 0);
	if (Card.TurbulenceScheduleTimes.Num() > 0)
	{
		Environment->SetStringField(TEXT("turbulence_schedule_delivery"),
			TEXT("per-step W20 only, held until the next entry; the seed and "
			     "the pinned severity are written exactly once (section 13)"));
	}
	Environment->SetBoolField(TEXT("orographic_follow_schedule"),
	                          Card.bOrographicFollowSchedule);
	Root->SetObjectField(TEXT("environment"), Environment);
	Root->SetArrayField(TEXT("frame_records"), FrameRecords);

	if (RunRecorder != nullptr && !RunRecorder->WriteToDisk())
	{
		return Fail(FString::Printf(TEXT("run telemetry did not write to '%s'"),
		                            *RunTelemetryPath));
	}
	if (RunRecorder != nullptr)
	{
		Root->SetStringField(TEXT("telemetry"), RunTelemetryPath);
	}

	FString Output;
	TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
	FJsonSerializer::Serialize(Root.ToSharedRef(), Writer);
	const FString ManifestPath = FPaths::Combine(OutputDirectory, TEXT("render.json"));
	if (!FFileHelper::SaveStringToFile(Output, *ManifestPath))
	{
		return Fail(FString::Printf(TEXT("could not write %s"), *ManifestPath));
	}
	UE_LOG(LogFlightSimRender, Display, TEXT("wrote %d frames and %s"),
	       Captured, *ManifestPath);

	Scenario.Teardown();
	return 0;
}
