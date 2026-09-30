#include "FlightSimRenderCommandlet.h"

#include "FlightSimCameraDirector.h"
#include "FlightSimOrographic.h"
#include "FlightSimSky.h"
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
#include "Materials/MaterialInstanceDynamic.h"
#include "ColorManagement/ColorSpace.h"
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
	// W5: the land-cover ID pass's post-process material (scripts/
	// ue_create_materials.py LANDCOVER_PARAMETERS: ClassMap, OriginX, OriginY,
	// CellX, CellY, GridWidth, GridHeight, TerrainStencil).
	constexpr const TCHAR* RenderLandcoverMaterialPath =
		TEXT("/Game/FlightSim/M_LandcoverID.M_LandcoverID");
	// I6 (gap S3): the ground-truth passes -passes=normal,velocity,albedo.
	// Each renders through a post-process material built by
	// scripts/ue_create_materials.py on the M_CustomStencilID pattern
	// (MD_PostProcess, blendable location "Replacing the Tonemapper", one
	// SceneTexture node into emissive): ESceneTextureId PPI_WorldNormal,
	// PPI_Velocity and PPI_BaseColor in UE 5.7. Absent -> the pass refuses
	// by name (labels.pass_material), like -labels does. The two SIGNED
	// textures reach the target as value * RenderPassSignedScale +
	// RenderPassSignedOffset (the script's SIGNED_SCALE / SIGNED_OFFSET,
	// pinned equal by test) because whether a tonemapper-replacing
	// emissive keeps a negative value through the FinalColorHDR readback
	// is not established here; the decode below inverts it.
	constexpr const TCHAR* RenderPassNormalMaterialPath =
		TEXT("/Game/FlightSim/M_WorldNormalPass.M_WorldNormalPass");
	constexpr const TCHAR* RenderPassVelocityMaterialPath =
		TEXT("/Game/FlightSim/M_VelocityPass.M_VelocityPass");
	constexpr const TCHAR* RenderPassBaseColorMaterialPath =
		TEXT("/Game/FlightSim/M_BaseColorPass.M_BaseColorPass");
	constexpr float RenderPassSignedScale = 0.5f;
	constexpr float RenderPassSignedOffset = 0.5f;
	// frame_NNNN_normal.png stores (n * 0.5 + 0.5) * 65535 per channel,
	// n the unit normal in the scene frame (north, east, up).
	constexpr float RenderPassNormalEncodeScale = 0.5f;
	constexpr float RenderPassNormalEncodeOffset = 0.5f;
	constexpr float RenderPassPngMax = 65535.0f;
	// The raw depth file is little-endian float32; every UE target is.
	// The flow file (frame_NNNN_flow.f32, I6) is declared the same way.
	static_assert(PLATFORM_LITTLE_ENDIAN, "frame_NNNN_depth.f32 is declared little-endian");

	// -- S4 (the sensing engine side) -----------------------------------
	// The linear passes (-passes=normal / -passes=albedo): SCS_Normal and
	// SCS_BaseColor captures into RTF_RGBA16f, written by WriteLinearF32
	// (the byte layout is stated in FlightSimRenderCommandlet.h) with
	// RenderLinearChannels values a pixel: the normal file holds the unit
	// normal in the SCENE frame RenderNormalAxes, the base colour file
	// linear R, G, B as the GBuffer holds it (no clamp). Sky pixels (+inf
	// in _depth.f32) are 0, 0, 0 in both.
	constexpr int32 RenderLinearChannels = 3;
	constexpr const TCHAR* RenderNormalAxes = TEXT("north,east,up");
	// What an SCS_Normal texel is, measured per frame on the geometry
	// pixels rather than assumed: "offset_half" (n * 0.5 + 0.5, as the I6
	// material pass writes) or "signed" (n itself). The encoding whose
	// decoded vectors are unit length (within RenderNormalUnitTolerance) on
	// at least RenderNormalUnitFraction of the geometry pixels wins; neither
	// refuses labels.normal_encoding by name.
	constexpr double RenderNormalUnitTolerance = 0.05;
	constexpr double RenderNormalUnitFraction = 0.5;
	// The fallback normal material (-normal-source=material): one
	// SceneTexture:WorldNormal node into emissive, NOT offset-encoded
	// (scripts/ue_create_materials.py M_WorldNormal).
	constexpr const TCHAR* RenderWorldNormalFallbackMaterialPath =
		TEXT("/Game/FlightSim/M_WorldNormal.M_WorldNormal");
	// The velocity cross-check (-velocity-check): SceneTexture:Velocity into
	// emissive, signed and unencoded, read back from RTF_RGBA32f. A
	// read-back beside the Python flow, never the truth.
	constexpr const TCHAR* RenderVelocityCheckMaterialPath =
		TEXT("/Game/FlightSim/M_Velocity.M_Velocity");
	// The calibration frame (-calibration): M_GreyCard is lit, fully rough,
	// non-metallic, specular 0 (a Lambertian), with two scalar parameters
	// (scripts/ue_create_materials.py GREY_CARD_*): Luminance -> emissive,
	// stated in cd/m^2 (one emissive unit = 1 cd/m^2 is the assumption the
	// emissive quad MEASURES), and Reflectance -> base colour.
	constexpr const TCHAR* RenderGreyCardMaterialPath =
		TEXT("/Game/FlightSim/M_GreyCard.M_GreyCard");
	constexpr const TCHAR* RenderGreyCardLuminanceParameter = TEXT("Luminance");
	constexpr const TCHAR* RenderGreyCardReflectanceParameter = TEXT("Reflectance");
	constexpr const TCHAR* RenderCalibrationPlanePath = TEXT("/Engine/BasicShapes/Plane.Plane");
	// core/capture/radiometry.py CALIBRATION_CONSTANT, LENS_ATTENUATION_DEFAULT
	// (used only when the console variable is absent, and said so),
	// GREY_CARD_REFLECTANCE; GREY_CARD_TOL is the verifier's 2 %.
	constexpr double RenderCalibrationConstant = 1.2;
	constexpr double RenderLensAttenuationDefault = 0.78;
	constexpr double RenderGreyCardReflectance = 0.18;
	constexpr double RenderCalibrationTolerance = 0.02;
	// The white Lambertian quad's reflectance (a stated white: 0.9, below
	// the 1.0 edge of the base-colour range).
	constexpr double RenderWhiteQuadReflectance = 0.9;
	// The quads sit this far along the calibration camera's axis, each
	// RenderCalibrationQuadFraction of the image height tall, centred at
	// -RenderCalibrationQuadOffset (emissive grey), 0 (slanted edge) and
	// +RenderCalibrationQuadOffset (white Lambertian) of the half-width.
	constexpr double RenderCalibrationDistanceM = 20.0;
	constexpr double RenderCalibrationQuadFraction = 0.25;
	constexpr double RenderCalibrationQuadOffset = 0.55;
	// ISO 12233's slant (core/capture/optics.py slanted_edge_image's 5 deg).
	constexpr double RenderSlantedEdgeAngleDeg = 5.0;
	// A quad's luminance is the mean over the inner half of its projected
	// box (each side inset by this fraction), away from its edges.
	constexpr double RenderCalibrationInset = 0.25;
	// core/scenario/solar.py SUN_LUX_MAX: nothing above the atmosphere is
	// brighter. And the unitless sun every Gate 6 clause was tuned on.
	constexpr double RenderSunLuxMax = 133100.0;
	constexpr double RenderEngineSunUnitless = 8.0;
	// -accumulate=K: at most this many sub-exposures a frame.
	constexpr int32 RenderAccumulateMax = 64;
	constexpr double RenderSubPixelBlurPx = 0.25;
	// The e-SFR's edge-spread oversampling (a quarter pixel).
	constexpr int32 RenderEsfrOversample = 4;
	static_assert(sizeof(float) == 4, "the linear .f32 files are declared float32");

	// A pixel of a world point through a capture's transform and FOV, and
	// whether the point is in front of it (ProjectToPixel's arithmetic,
	// which says only whether the pixel is inside the frame).
	bool RenderPixelInFront(const USceneCaptureComponent2D* Capture, int32 Width,
	                        int32 Height, const FVector& WorldCm, FVector2D& OutPixel)
	{
		const FVector Local =
			Capture->GetComponentTransform().InverseTransformPosition(WorldCm);
		if (Local.X <= 1.0)
		{
			OutPixel = FVector2D(-1.0, -1.0);
			return false;
		}
		const double HalfWidthTan = FMath::Tan(FMath::DegreesToRadians(Capture->FOVAngle * 0.5));
		const double HalfHeightTan = HalfWidthTan * Height / double(Width);
		OutPixel.X = Width * 0.5 * (1.0 + (Local.Y / Local.X) / HalfWidthTan);
		OutPixel.Y = Height * 0.5 * (1.0 - (Local.Z / Local.X) / HalfHeightTan);
		return true;
	}

	// Rec. 709 luminance of a linear working-colour-space pixel.
	double RenderLuminance709(const FLinearColor& C)
	{
		return 0.2126 * C.R + 0.7152 * C.G + 0.0722 * C.B;
	}

	// IEC 61966-2-1 sRGB encoding of a linear value in [0, 1], 8-bit.
	uint8 RenderSrgb8(double Linear)
	{
		const double C = FMath::Clamp(Linear, 0.0, 1.0);
		const double Encoded = C <= 0.0031308 ? 12.92 * C : 1.055 * FMath::Pow(C, 1.0 / 2.4) - 0.055;
		return static_cast<uint8>(FMath::Clamp(FMath::RoundToInt(Encoded * 255.0), 0, 255));
	}

	// The 95th percentile (nearest rank below) of a list, 0 for none.
	double RenderPercentile95(TArray<float>& Values)
	{
		if (Values.Num() == 0)
		{
			return 0.0;
		}
		Values.Sort();
		return Values[FMath::Clamp(static_cast<int32>(0.95 * (Values.Num() - 1)), 0, Values.Num() - 1)];
	}

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

	// I6: a 16-bit RGBA PNG through the same wrapper call the 16-bit depth
	// PNG uses (the engine's PNG wrapper writes Gray, RGBA or BGRA -- not
	// RGB -- so the fourth channel is a constant 65535 and every reader
	// takes the first three). Values are native uint16, interleaved
	// R G B A, row-major.
	bool RenderWriteRgba16Png(const FString& Path, const TArray<uint16>& Rgba,
	                          int32 Width, int32 Height)
	{
		if (Rgba.Num() != Width * Height * 4)
		{
			return false;
		}
		IImageWrapperModule& Module =
			FModuleManager::LoadModuleChecked<IImageWrapperModule>(TEXT("ImageWrapper"));
		TSharedPtr<IImageWrapper> Png = Module.CreateImageWrapper(EImageFormat::PNG);
		if (!Png.IsValid()
		    || !Png->SetRaw(Rgba.GetData(), static_cast<int64>(Rgba.Num()) * sizeof(uint16),
		                    Width, Height, ERGBFormat::RGBA, 16))
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

// -- S4: the calibration chain, the 0.25 px rule, the linear writer, the e-SFR --

double UFlightSimRenderCommandlet::LuminancePerUnit(double Ev100, double ExposureCompensationEv,
                                                    double LensAttenuation)
{
	// core/capture/radiometry.py luminance_per_unit, re-implemented, not
	// imported (tests/test_ue_passes_source.py pins this expression).
	return RenderCalibrationConstant * LensAttenuation * FMath::Pow(2.0, Ev100 - ExposureCompensationEv);
}

double UFlightSimRenderCommandlet::LambertianLuminance(double IlluminanceLux, double Reflectance)
{
	return Reflectance * IlluminanceLux / UE_DOUBLE_PI;
}

int32 UFlightSimRenderCommandlet::AccumulationCount(double PredictedBlurPx, int32 RequestedK)
{
	return PredictedBlurPx < RenderSubPixelBlurPx ? 1 : FMath::Max(1, RequestedK);
}

bool UFlightSimRenderCommandlet::WriteLinearF32(const FString& Path, const TArray<float>& Values,
                                                int32 Width, int32 Height, int32 Channels)
{
	// The layout is the header's: little-endian float32 (static_assert
	// above), no header, row-major from the top-left, Channels interleaved.
	const int64 Expected = static_cast<int64>(Width) * Height * Channels;
	if (Width <= 0 || Height <= 0 || Channels <= 0 || Values.Num() != Expected)
	{
		return false;
	}
	TArray64<uint8> Bytes;
	Bytes.SetNumUninitialized(Expected * static_cast<int64>(sizeof(float)));
	FMemory::Memcpy(Bytes.GetData(), Values.GetData(), Bytes.Num());
	return FFileHelper::SaveArrayToFile(Bytes, *Path);
}

double UFlightSimRenderCommandlet::EsfrMtf50(const TArray<float>& Luminance, int32 Width, int32 Height,
                                             int32 U0, int32 V0, int32 U1, int32 V1)
{
	U0 = FMath::Clamp(U0, 0, Width);
	U1 = FMath::Clamp(U1, 0, Width);
	V0 = FMath::Clamp(V0, 0, Height);
	V1 = FMath::Clamp(V1, 0, Height);
	const int32 CropWidth = U1 - U0;
	const int32 CropHeight = V1 - V0;
	if (Luminance.Num() != Width * Height || CropWidth < 8 || CropHeight < 8)
	{
		return -1.0;
	}
	// 1. Each row's edge: the half level between the row's 10th and 90th
	// percentile levels, the first crossing linearly interpolated between
	// pixel centres (x + 0.5).
	TArray<double> EdgeX, EdgeY;
	TArray<float> Row, Sorted;
	for (int32 V = V0; V < V1; ++V)
	{
		Row.Reset();
		for (int32 U = U0; U < U1; ++U)
		{
			Row.Add(Luminance[V * Width + U]);
		}
		Sorted = Row;
		Sorted.Sort();
		const double Low = Sorted[CropWidth / 10];
		const double High = Sorted[(CropWidth * 9) / 10];
		if (!(High - Low > 1.0e-6))
		{
			continue;
		}
		const double Half = 0.5 * (Low + High);
		for (int32 i = 1; i < CropWidth; ++i)
		{
			const double A = Row[i - 1] - Half;
			const double B = Row[i] - Half;
			if ((A < 0.0) != (B < 0.0))
			{
				EdgeX.Add(U0 + (i - 1) + 0.5 + A / (A - B));
				EdgeY.Add(V + 0.5);
				break;
			}
		}
	}
	const int32 Rows = EdgeX.Num();
	if (Rows < 3)
	{
		return -1.0;
	}
	// 2. The edge line x = Intercept + Slope * y by least squares.
	double Sy = 0.0, Sx = 0.0, Syy = 0.0, Sxy = 0.0;
	for (int32 i = 0; i < Rows; ++i)
	{
		Sy += EdgeY[i];
		Sx += EdgeX[i];
		Syy += EdgeY[i] * EdgeY[i];
		Sxy += EdgeX[i] * EdgeY[i];
	}
	const double Denominator = Rows * Syy - Sy * Sy;
	if (FMath::Abs(Denominator) < 1.0e-12)
	{
		return -1.0;
	}
	const double Slope = (Rows * Sxy - Sy * Sx) / Denominator;
	const double Intercept = (Sx - Slope * Sy) / Rows;
	const double NormalLength = FMath::Sqrt(1.0 + Slope * Slope);
	// 3. The edge spread function: every crop pixel's signed distance from
	// the line along its normal, binned at 1 / RenderEsfrOversample px.
	double MinDistance = TNumericLimits<double>::Max();
	double MaxDistance = -TNumericLimits<double>::Max();
	TArray<double> Distances;
	Distances.SetNumUninitialized(CropWidth * CropHeight);
	for (int32 V = V0; V < V1; ++V)
	{
		for (int32 U = U0; U < U1; ++U)
		{
			const double D = ((U + 0.5) - (Intercept + Slope * (V + 0.5))) / NormalLength;
			Distances[(V - V0) * CropWidth + (U - U0)] = D;
			MinDistance = FMath::Min(MinDistance, D);
			MaxDistance = FMath::Max(MaxDistance, D);
		}
	}
	const int32 Bins = FMath::FloorToInt((MaxDistance - MinDistance) * RenderEsfrOversample) + 1;
	if (Bins < 8)
	{
		return -1.0;
	}
	TArray<double> Sum, Esf;
	TArray<int32> Count;
	Sum.SetNumZeroed(Bins);
	Count.SetNumZeroed(Bins);
	for (int32 V = V0; V < V1; ++V)
	{
		for (int32 U = U0; U < U1; ++U)
		{
			const int32 Bin = FMath::Clamp(FMath::FloorToInt(
				(Distances[(V - V0) * CropWidth + (U - U0)] - MinDistance) * RenderEsfrOversample), 0, Bins - 1);
			Sum[Bin] += Luminance[V * Width + U];
			++Count[Bin];
		}
	}
	Esf.SetNumZeroed(Bins);
	int32 LastFilled = -1;
	for (int32 i = 0; i < Bins; ++i)
	{
		if (Count[i] > 0)
		{
			Esf[i] = Sum[i] / Count[i];
			// An empty run between two filled bins is filled linearly.
			for (int32 j = LastFilled + 1; LastFilled >= 0 && j < i; ++j)
			{
				Esf[j] = Esf[LastFilled] + (Esf[i] - Esf[LastFilled]) * (j - LastFilled) / double(i - LastFilled);
			}
			if (LastFilled < 0)
			{
				for (int32 j = 0; j < i; ++j)
				{
					Esf[j] = Esf[i];
				}
			}
			LastFilled = i;
		}
	}
	for (int32 j = LastFilled + 1; LastFilled >= 0 && j < Bins; ++j)
	{
		Esf[j] = Esf[LastFilled];
	}
	// 4. The line spread function (finite difference; the edge's rise is
	// taken as positive) under a Hamming window centred on its centroid.
	const int32 Lsfs = Bins - 1;
	TArray<double> Lsf;
	Lsf.SetNumZeroed(Lsfs);
	double Total = 0.0, Moment = 0.0;
	for (int32 i = 0; i < Lsfs; ++i)
	{
		Lsf[i] = Esf[i + 1] - Esf[i];
		Total += Lsf[i];
	}
	if (FMath::Abs(Total) < 1.0e-12)
	{
		return -1.0;
	}
	for (int32 i = 0; i < Lsfs; ++i)
	{
		Lsf[i] /= Total;
		Moment += i * Lsf[i];
	}
	const double Centre = Moment;
	const double HalfWindow = FMath::Max(Centre, Lsfs - 1 - Centre) + 1.0;
	for (int32 i = 0; i < Lsfs; ++i)
	{
		Lsf[i] *= 0.54 + 0.46 * FMath::Cos(UE_DOUBLE_PI * (i - Centre) / HalfWindow);
	}
	// 5. The MTF by a DFT, normalised at zero frequency; MTF50 at the first
	// fall through one half, linearly interpolated. Bin k is k *
	// RenderEsfrOversample / Lsfs cycles per pixel.
	auto Magnitude = [&](int32 K) -> double
	{
		double Re = 0.0, Im = 0.0;
		for (int32 i = 0; i < Lsfs; ++i)
		{
			const double Phase = -2.0 * UE_DOUBLE_PI * K * i / Lsfs;
			Re += Lsf[i] * FMath::Cos(Phase);
			Im += Lsf[i] * FMath::Sin(Phase);
		}
		return FMath::Sqrt(Re * Re + Im * Im);
	};
	const double Dc = Magnitude(0);
	if (!(Dc > 0.0))
	{
		return -1.0;
	}
	double Previous = 1.0;
	for (int32 K = 1; K <= Lsfs / 2; ++K)
	{
		const double Mtf = Magnitude(K) / Dc;
		if (Mtf < 0.5)
		{
			const double Fraction = (Previous - 0.5) / (Previous - Mtf);
			return (K - 1 + Fraction) * RenderEsfrOversample / double(Lsfs);
		}
		Previous = Mtf;
	}
	return (Lsfs / 2) * RenderEsfrOversample / double(Lsfs);
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
		            "[-passes=normal,velocity,albedo] [-width=960] [-height=540] "
		            "[-calibration] [-sun-lux=<lux>] [-accumulate=<K>] [-velocity-check] "
		            "[-normal-source=scs|material] [-scene=<scene document>] "
		            "[-quality=measure|beauty] [-warmup=N]"));
		return 1;
	}
	// Visual plan V0. "measure" is every render this project has
	// measured, unchanged: same resolution default, same two warm-up
	// captures, engine-default GI/reflections/AA/shadows. "beauty" turns
	// on the modern renderer per capture (Lumen GI + reflections as
	// post-process overrides, TSR, virtual shadow maps), a 1080p default
	// and a longer warm-up so temporal history converges before frame 0.
	// Beauty is NOT a measured configuration until Gate 6 passes under it
	// on the rendering machine (experiments/gate6_visual.py --quality
	// beauty); the manifest says which one produced the frames.
	FString Quality = TEXT("measure");
	FParse::Value(*Params, TEXT("quality="), Quality);
	if (Quality != TEXT("measure") && Quality != TEXT("beauty"))
	{
		UE_LOG(LogFlightSimRender, Error,
		       TEXT("-quality=%s is not one of measure, beauty"), *Quality);
		return 1;
	}
	const bool bBeauty = Quality == TEXT("beauty");
	double FramesPerSecond = 5.0;
	int32 Width = bBeauty ? 1920 : 960;
	int32 Height = bBeauty ? 1080 : 540;
	FParse::Value(*Params, TEXT("fps="), FramesPerSecond);
	FParse::Value(*Params, TEXT("width="), Width);
	FParse::Value(*Params, TEXT("height="), Height);
	// Discarded warm-up captures (see the loop before the first frame).
	// Two is the measured minimum for a non-blank frame and is a floor:
	// fewer would put black frames into the run. Beauty wants more, so
	// TSR and Lumen have history before anything is kept.
	int32 WarmupCaptures = bBeauty ? 16 : 2;
	FParse::Value(*Params, TEXT("warmup="), WarmupCaptures);
	WarmupCaptures = FMath::Max(WarmupCaptures, 2);

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
	// I6 (gap S3): -passes=normal,velocity,albedo -- the ground-truth
	// passes beside the label bundle, each optional, none by default (so
	// a run without the flag is byte-for-byte the previous one). Only the
	// words are read here; an unknown word and -passes without -labels
	// are refused by name once Fail exists (below the scene build).
	FString PassesArg;
	FParse::Value(*Params, TEXT("passes="), PassesArg);
	bool bPassNormal = false, bPassVelocity = false, bPassAlbedo = false;
	FString UnknownPass;
	{
		TArray<FString> PassWords;
		PassesArg.ParseIntoArray(PassWords, TEXT(","), true);
		for (FString& Word : PassWords)
		{
			Word.TrimStartAndEndInline();
			if (Word == TEXT("normal")) { bPassNormal = true; }
			else if (Word == TEXT("velocity")) { bPassVelocity = true; }
			else if (Word == TEXT("albedo")) { bPassAlbedo = true; }
			else if (UnknownPass.IsEmpty()) { UnknownPass = Word; }
		}
	}
	const bool bPasses = bPassNormal || bPassVelocity || bPassAlbedo;
	// S4 (the sensing engine side): the opt-ins core/render/flags.py
	// sensing_flags builds (-calibration, -sun-lux=, -accumulate=) and two
	// switches of this commandlet's own (-velocity-check, -normal-source=).
	// Each is absent by default, so a run without them is byte-for-byte the
	// previous one; each is refused by name below once Fail exists.
	const bool bCalibration = FParse::Param(*Params, TEXT("calibration"));
	double SunLuxFlag = 0.0;
	const bool bSunLuxFlag = FParse::Value(*Params, TEXT("sun-lux="), SunLuxFlag);
	int32 AccumulateRequested = 0;
	const bool bAccumulate = FParse::Value(*Params, TEXT("accumulate="), AccumulateRequested);
	const bool bVelocityCheck = FParse::Param(*Params, TEXT("velocity-check"));
	FString NormalSource = TEXT("scs");
	FParse::Value(*Params, TEXT("normal-source="), NormalSource);
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
	// W5: -scene=<scene document> (scripts/ue_build_scene.py): the Landscape
	// scene level in place of the procedural terrain, matched against the
	// card's world block at load (FlightSimVisualScene LoadSceneLevel). Absent
	// = the procedural route, byte-for-byte the previous one.
	FString ScenePath;
	FParse::Value(*Params, TEXT("scene="), ScenePath);
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
	// The physical sky (core/sky/plan.py): sun, moon, stars, clouds, EV100
	// camera, Lumen + VSM, per-preset lens. Replaces -sun-*/-exposure-bias;
	// absent, the calibrated legacy scene renders unchanged.
	FString SkyPlanPath;
	FParse::Value(*Params, TEXT("sky="), SkyPlanPath);
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

	FFlightSimSkyPlan SkyPlan;
	const bool bPhysicalSky = !SkyPlanPath.IsEmpty();
	if (bPhysicalSky)
	{
		FString SkyError;
		if (!bVisual || bSunOverride || bAutoExposure)
		{
			UE_LOG(LogFlightSimRender, Error,
			       TEXT("-sky needs -Visual and replaces -sun-elev/-sun-azim and "
			            "-AutoExposure; refusing an ambiguous sky"));
			return 1;
		}
		if (!FFlightSimSkyPlan::Load(SkyPlanPath, SkyPlan, SkyError))
		{
			UE_LOG(LogFlightSimRender, Error, TEXT("%s"), *SkyError);
			return 1;
		}
		FFlightSimSky::EnableRendererFeatures();
	}

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
	// W3: the weather look's rain rate and its extinction -- recorded, not
	// applied here (the streaks come from the card's world look block, the
	// extinction is already inside fog_extinction_per_m).
	double LookRainRateMmh = 0.0, LookRainExtinction = 0.0;
	bool bLookRainRate = false, bLookRainExtinction = false;
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
			bLookRainRate = CardLook->TryGetNumberField(TEXT("precipitation_rate_mmh"), LookRainRateMmh);
			bLookRainExtinction = CardLook->TryGetNumberField(TEXT("rain_extinction_per_m"),
			                                                  LookRainExtinction);
		}
	}
	// W5: the card as JSON for the world engine side -- its world block (the
	// scene is matched against it), its look block (the moon, the stars, the
	// rain, the drift), its latitude (the starfield's pole). A card with
	// neither block and no -scene= renders byte-identically to before.
	TSharedPtr<FJsonObject> WorldCardRoot;
	{
		FString WorldCardText;
		if (FFileHelper::LoadFileToString(WorldCardText, *ScenarioPath))
		{
			const TSharedRef<TJsonReader<>> WorldReader = TJsonReaderFactory<>::Create(WorldCardText);
			FJsonSerializer::Deserialize(WorldReader, WorldCardRoot);
		}
	}
	const bool bWorldAsked = !ScenePath.IsEmpty() ||
		(WorldCardRoot.IsValid() && (WorldCardRoot->HasField(TEXT("world")) ||
		                             WorldCardRoot->HasField(TEXT("look"))));
	if (!ScenePath.IsEmpty() && !(bVisual && bGeorefTerrain))
	{
		return Fail(FString::Printf(
			TEXT("world.scene_missing: -scene=%s loads a Landscape into the georeferenced visual ")
			TEXT("scene; pass -Visual -GeorefTerrain (the void tier has no world)"), *ScenePath));
	}
	TArray<FString> LookProbeOverrides;
	// S4: the sun in lux (0 = the unitless 8.0 sun every Gate 6 clause was
	// tuned on) and where the number came from.
	double AppliedSunLux = 0.0;
	FString SunLuxSource;
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
		// S4: the sun's intensity in lux -- the card's look.sun_lux when the
		// card states one, -sun-lux= (core/render/flags.py, handed the
		// spec's scene.sun_lux or the clear-sky model) over it. Refused by
		// name outside (0, 133100] lx, as the Python side refuses it.
		if (CardLook.IsValid())
		{
			double CardSunLux = 0.0;
			if (CardLook->TryGetNumberField(TEXT("sun_lux"), CardSunLux))
			{
				AppliedSunLux = CardSunLux;
				SunLuxSource = LookSource + TEXT(".sun_lux");
			}
		}
		if (bSunLuxFlag)
		{
			AppliedSunLux = SunLuxFlag;
			SunLuxSource = FString::Printf(TEXT("-sun-lux=%g"), SunLuxFlag);
		}
		if (!SunLuxSource.IsEmpty() && !(AppliedSunLux > 0.0 && AppliedSunLux <= RenderSunLuxMax))
		{
			return Fail(FString::Printf(
				TEXT("sensing.sun_lux: a sun of %g lux (%s) cannot be lit; it must be a positive ")
				TEXT("number no brighter than the %.0f lux of the sun above the atmosphere"),
				AppliedSunLux, *SunLuxSource, RenderSunLuxMax));
		}
		SceneOptions.SunLux = AppliedSunLux;
		SceneOptions.SunLuxSource = SunLuxSource;
		SceneOptions.bStarsRequested = bStarsFlag;
		SceneOptions.bMoonRequested = bMoonFlag;
		if (bStarsFlag) { LookProbeOverrides.Add(TEXT("stars")); }
		if (bMoonFlag) { LookProbeOverrides.Add(TEXT("moon")); }
		// W5: the scene level, the card the world is matched against and
		// drawn from, and where the cached star catalogue lives (the repo's
		// assets/stars, one level above the project).
		SceneOptions.SceneDocumentPath = ScenePath;
		SceneOptions.Card = WorldCardRoot;
		SceneOptions.StarCataloguePath = FPaths::ConvertRelativePathToFull(
			FPaths::Combine(FPaths::ProjectDir(), TEXT(".."), TEXT("assets"), TEXT("stars"),
			                TEXT("bsc5-short.json")));
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
		if (bPhysicalSky)
		{
			SceneOptions.SkyPlan = &SkyPlan;
		}
		if (!VisualScene.Build(World, SceneOptions, Error)) { return Fail(Error); }
	}
	else
	{
		ADirectionalLight* Sun = World->SpawnActor<ADirectionalLight>();
		Sun->GetLightComponent()->SetMobility(EComponentMobility::Movable);
		Sun->SetActorRotation(FRotator(-35.0, 140.0, 0.0));
		Sun->GetLightComponent()->SetIntensity(8.0f);
		if (bSunLuxFlag)
		{
			// S4: Gate 5's void keeps its studio key light (the silhouette
			// measurements depend on it); the lux is recorded as not applied
			// (render.json scene.sun_lux_applied false), never silently.
			UE_LOG(LogFlightSimRender, Warning,
			       TEXT("-sun-lux=%g is not applied: the void tier (no -Visual) keeps Gate 5's key light"),
			       SunLuxFlag);
		}

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
	// S4: the card's shutter, when the card states the triple: the window
	// -accumulate= spreads its sub-exposures over (0 = none stated).
	double ExposureShutterSeconds = 0.0;
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
		if (bPhysicalSky)
		{
			// The physical sky's plan (-sky=) carries the camera: EV100 from
			// modelled illuminance, lens effects per preset, Lumen + VSM.
			FFlightSimSky::ApplyPostProcess(Capture->PostProcessSettings, SkyPlan);
			FFlightSimSky::ApplyShowFlags(Capture->ShowFlags);
			ExposureMode = TEXT("physical_sky");
			ExposureSource = TEXT("-sky= plan (core/sky/plan.py) EV100");
		}
		else if (bVisual && !bAutoExposure)
		{
			const double* LookValue =
				CardCameraId.IsEmpty() ? nullptr : LookEv100.Find(CardCameraId);
			if (bCardExposure)
			{
				AppliedEv100 = FFlightSimVisualScene::ApplyPhysicalExposure(
					Capture, CardApertureF, CardShutterS, CardIso);
				bAppliedEv100 = true;
				ExposureShutterSeconds = CardShutterS;
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
	// Beauty's renderer switches. GI and reflections are per-view
	// overrides on this capture; AA and the shadow method are renderer
	// cvars, set by code for this process only (a commandlet run is one
	// render) and read BACK for the manifest, so the record states what
	// the renderer was actually set to rather than what was asked for.
	int32 AntiAliasingMethod = -1;
	int32 VirtualShadowMaps = -1;
	auto ReadCvar = [](const TCHAR* Name) -> int32
	{
		IConsoleVariable* Variable =
			IConsoleManager::Get().FindConsoleVariable(Name);
		return Variable != nullptr ? Variable->GetInt() : -1;
	};
	if (bVisual && bBeauty)
	{
		FFlightSimVisualScene::ApplyBeautyPostProcess(Capture);
		auto SetCvar = [](const TCHAR* Name, int32 Value)
		{
			if (IConsoleVariable* Variable =
				IConsoleManager::Get().FindConsoleVariable(Name))
			{
				Variable->Set(Value, ECVF_SetByCode);
			}
			else
			{
				UE_LOG(LogFlightSimRender, Warning,
				       TEXT("renderer cvar %s not found on this build; the "
				            "manifest records -1 for it"), Name);
			}
		};
		SetCvar(TEXT("r.AntiAliasingMethod"), 4);       // TSR
		SetCvar(TEXT("r.Shadow.Virtual.Enable"), 1);    // VSM
	}
	AntiAliasingMethod = ReadCvar(TEXT("r.AntiAliasingMethod"));
	VirtualShadowMaps = ReadCvar(TEXT("r.Shadow.Virtual.Enable"));
	if (bHideAircraft)
	{
		Capture->HiddenActors.Add(Scenario.Aircraft);
	}
	Capture->RegisterComponent();
	// W5: the rain streaks, on the BEAUTY capture only (the label captures
	// below never receive a look blendable), for this camera's streak on the
	// card (cameras[N].camera_id under consume-poses; the card's only streak
	// otherwise). A card without a rain rate adds nothing.
	if (bVisual)
	{
		FString RainCameraId;
		const TArray<TSharedPtr<FJsonValue>>* RainCameras = nullptr;
		if (bConsumePoses && WorldCardRoot.IsValid() &&
		    WorldCardRoot->TryGetArrayField(TEXT("cameras"), RainCameras) && RainCameras != nullptr &&
		    RainCameras->IsValidIndex(ConsumedCameraIndex))
		{
			const TSharedPtr<FJsonObject> RainCamera = (*RainCameras)[ConsumedCameraIndex]->AsObject();
			if (RainCamera.IsValid())
			{
				RainCamera->TryGetStringField(TEXT("camera_id"), RainCameraId);
			}
		}
		if (!VisualScene.ApplyRainToBeauty(Capture, RainCameraId, Error))
		{
			return Fail(Error);
		}
	}

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
	// W5: the land-cover ID pass (M_LandcoverID), under -labels on a -scene=
	// render whose scene carries a class map: one more AA-free capture, the
	// class code per pixel as frame_NNNN_landcover_id.png (render.json
	// labels.landcover_png, graded against the checker's own unprojection by
	// core/capture/verify.py landcover_vs_geometry).
	UTextureRenderTarget2D* LandcoverTarget = nullptr;
	USceneCaptureComponent2D* LabelLandcover = nullptr;
	// I6 (gap S3): the ground-truth pass captures, built inside the label
	// block below because they ride ConfigureLabelCapture (AA-free, no
	// fog, no atmosphere, no cloud, no translucency) and are graded
	// against the label bundle's depth and ID image.
	UMaterialInterface* PassNormalMaterial = nullptr;
	UMaterialInterface* PassVelocityMaterial = nullptr;
	UMaterialInterface* PassAlbedoMaterial = nullptr;
	UTextureRenderTarget2D* PassNormalTarget = nullptr;
	UTextureRenderTarget2D* PassVelocityTarget = nullptr;
	UTextureRenderTarget2D* PassAlbedoTarget = nullptr;
	USceneCaptureComponent2D* PassNormal = nullptr;
	USceneCaptureComponent2D* PassVelocity = nullptr;
	USceneCaptureComponent2D* PassAlbedo = nullptr;
	if (!UnknownPass.IsEmpty())
	{
		return Fail(FString::Printf(
			TEXT("labels.pass_unknown: -passes names '%s'; the passes this build ")
			TEXT("writes are normal, velocity and albedo"), *UnknownPass));
	}
	if (bPasses && !bLabels)
	{
		return Fail(TEXT("labels.pass_needs_labels: -passes rides the label-pass route ")
		            TEXT("(the AA-free captures, the depth the normals are checked ")
		            TEXT("against, the ID image the flow is sampled under); pass ")
		            TEXT("-labels too"));
	}
	// -- S4: the linear passes, the velocity cross-check, the accumulation
	// and the calibration frame -- each refused by name before anything
	// flies, never degraded to a frame that says less than it was asked.
	UTextureRenderTarget2D* LinearNormalTarget = nullptr;
	UTextureRenderTarget2D* LinearBaseColorTarget = nullptr;
	UTextureRenderTarget2D* VelocityCheckTarget = nullptr;
	USceneCaptureComponent2D* LinearNormal = nullptr;
	USceneCaptureComponent2D* LinearBaseColor = nullptr;
	USceneCaptureComponent2D* VelocityCheck = nullptr;
	FString LinearNormalSource;
	if (NormalSource != TEXT("scs") && NormalSource != TEXT("material"))
	{
		return Fail(FString::Printf(
			TEXT("labels.normal_encoding: -normal-source='%s' is neither scs (the SCS_Normal ")
			TEXT("capture) nor material (the M_WorldNormal fallback)"), *NormalSource));
	}
	if (bVelocityCheck && !bLabels)
	{
		return Fail(TEXT("labels.velocity_check: -velocity-check rides the label-pass route (the ")
		            TEXT("AA-free captures, the depth its statistics are taken over); pass -labels too"));
	}
	if (bVelocityCheck && bPassVelocity)
	{
		return Fail(TEXT("labels.velocity_check: -velocity-check and -passes=velocity each need the ")
		            TEXT("first scene render after the step (the engine keeps a primitive's previous ")
		            TEXT("transform for one render only); ask for one of them"));
	}
	if (bAccumulate)
	{
		if (AccumulateRequested < 1 || AccumulateRequested > RenderAccumulateMax)
		{
			return Fail(FString::Printf(
				TEXT("sensing.accumulate: -accumulate=%d is not a whole number of sub-exposures ")
				TEXT("from 1 to %d"), AccumulateRequested, RenderAccumulateMax));
		}
		if (!(ExposureShutterSeconds > 0.0))
		{
			return Fail(TEXT("sensing.accumulate: -accumulate spreads its sub-exposures over the ")
			            TEXT("shutter, and this camera states none (the card's cameras[N].exposure ")
			            TEXT("triple, on -Visual without -AutoExposure); the window is never assumed"));
		}
		if (bPassVelocity || bVelocityCheck)
		{
			return Fail(TEXT("sensing.accumulate: the sub-exposures move the actors between scene ")
			            TEXT("renders and a velocity pass reads motion from the last one; ask for the ")
			            TEXT("accumulation or a velocity pass, not both"));
		}
	}
	UMaterialInterface* CalibrationGreyCard = nullptr;
	UStaticMesh* CalibrationPlane = nullptr;
	if (bCalibration)
	{
		if (!bVisual)
		{
			return Fail(TEXT("sensing.calibration: -calibration needs -Visual; the calibration ")
			            TEXT("frame's white quad is lit by the scene's sun"));
		}
		if (!bAppliedEv100)
		{
			return Fail(FString::Printf(
				TEXT("sensing.calibration: -calibration needs the manual EV100 exposure (the card's ")
				TEXT("cameras[N].exposure or look.ev100); this pass's exposure is %s, which no ")
				TEXT("luminance chain describes"), *ExposureMode));
		}
		if (!(AppliedSunLux > 0.0))
		{
			return Fail(TEXT("sensing.calibration: -calibration needs the sun in lux (-sun-lux=); ")
			            TEXT("the unitless 8.0 sun has no luminance to predict"));
		}
		CalibrationGreyCard = LoadObject<UMaterialInterface>(nullptr, RenderGreyCardMaterialPath);
		if (CalibrationGreyCard == nullptr)
		{
			return Fail(FString::Printf(
				TEXT("sensing.calibration: -calibration needs the material %s (lit, fully rough, ")
				TEXT("specular 0, the Luminance and Reflectance parameters), which ")
				TEXT("scripts/ue_create_materials.py builds"), RenderGreyCardMaterialPath));
		}
		CalibrationPlane = LoadObject<UStaticMesh>(nullptr, RenderCalibrationPlanePath);
		if (CalibrationPlane == nullptr || VisualScene.Sun == nullptr)
		{
			return Fail(FString::Printf(
				TEXT("sensing.calibration: the calibration quads need %s and the scene's sun; %s"),
				RenderCalibrationPlanePath,
				CalibrationPlane == nullptr ? TEXT("the plane did not load") : TEXT("the scene has no sun")));
		}
	}
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

		// Every primitive component in the world carries the stencil of the
		// object it belongs to: an aircraft actor's its own int_id, every
		// other primitive (terrain, ground plane, funnel) the terrain's.
		// Editor-only and hidden-in-game components draw in no capture and
		// get none.
		//
		// W5: the loop runs over UPrimitiveComponent, not UMeshComponent: a
		// ULandscapeComponent is a primitive and not a mesh, so the old loop
		// left a scene level's Landscape without the terrain id (blueprint
		// section 4). An actor the scene level tagged FlightSim.vegetation /
		// FlightSim.building carries the card's vegetation:all /
		// building:all int_id (one aggregate each: the 8-bit stencil has no
		// room for instances); a beauty-only actor (the starfield) carries
		// none. A tagged actor whose aggregate the card does not name is
		// refused (annotation.identity), never labelled terrain.
		int32 LabelVegetationIntId = 0;
		int32 LabelBuildingIntId = 0;
		for (const FRenderLabelledObject& Entry : Labelled)
		{
			if (Entry.Id == FlightSimWorld::VegetationObjectId)
			{
				LabelVegetationIntId = Entry.IntId;
			}
			else if (Entry.Id == FlightSimWorld::BuildingObjectId)
			{
				LabelBuildingIntId = Entry.IntId;
			}
		}
		TMap<int32, int32> StencilCounts;
		for (TActorIterator<AActor> It(World); It; ++It)
		{
			if (VisualScene.BeautyOnlyActors.Contains(*It))
			{
				continue;
			}
			int32 IntId = LabelTerrainIntId;
			const TCHAR* Aggregate = nullptr;
			if (It->ActorHasTag(FName(FlightSimWorld::VegetationTag)))
			{
				IntId = LabelVegetationIntId;
				Aggregate = FlightSimWorld::VegetationObjectId;
			}
			else if (It->ActorHasTag(FName(FlightSimWorld::BuildingTag)))
			{
				IntId = LabelBuildingIntId;
				Aggregate = FlightSimWorld::BuildingObjectId;
			}
			if (Aggregate != nullptr && IntId <= 0)
			{
				return Fail(FString::Printf(
					TEXT("annotation.identity: the scene level carries '%s' tagged for %s, and the ")
					TEXT("card's objects[] names no %s; its pixels would carry another object's id"),
					*It->GetName(), Aggregate, Aggregate));
			}
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
			TInlineComponentArray<UPrimitiveComponent*> Primitives;
			It->GetComponents(Primitives);
			for (UPrimitiveComponent* Primitive : Primitives)
			{
				if (Primitive == nullptr || Primitive->IsEditorOnly() || Primitive->bHiddenInGame)
				{
					continue;
				}
				Primitive->SetRenderCustomDepth(true);
				Primitive->SetCustomDepthStencilValue(IntId);
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
			// W5: the world look is the beauty's alone -- the starfield
			// sphere is hidden here, and no look blendable (the rain) is
			// ever added to a label capture -- so mask, class and depth are
			// byte-identical with the world look on and off.
			Label->HiddenActors.Append(VisualScene.BeautyOnlyActors);
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
		// W5: the land-cover ID pass. M_LandcoverID (post-process, replacing
		// the tonemapper) reconstructs each pixel's world position from its
		// depth, carries it onto the bake grid with the registration the scene
		// load MEASURED (FFlightSimLandcoverPass), samples the class-code
		// raster nearest-filtered, and emits the code where the custom stencil
		// is the terrain's int_id (0 elsewhere: sky, aircraft, buildings,
		// vegetation). Refused by name when the scene asks for it and the
		// material or the class map is absent.
		const TSharedPtr<FJsonObject>* LandcoverAsked = nullptr;
		const bool bLandcoverAsked = VisualScene.WorldApplied.IsValid() &&
			VisualScene.WorldApplied->TryGetObjectField(TEXT("land_cover"), LandcoverAsked) &&
			LandcoverAsked != nullptr && (*LandcoverAsked)->GetBoolField(TEXT("asked"));
		if (bLandcoverAsked)
		{
			UMaterialInterface* LandcoverMaterial =
				LoadObject<UMaterialInterface>(nullptr, RenderLandcoverMaterialPath);
			if (LandcoverMaterial == nullptr || !VisualScene.Landcover.bReady)
			{
				return Fail(FString::Printf(
					TEXT("labels.landcover_pass: the scene carries land cover and the ID pass needs %s ")
					TEXT("(scripts/ue_create_materials.py) and the class map %s (scripts/")
					TEXT("ue_build_scene.py); %s"),
					RenderLandcoverMaterialPath, *VisualScene.Landcover.ClassMapAsset,
					LandcoverMaterial == nullptr ? TEXT("the material did not load")
					                             : TEXT("the class map did not load")));
			}
			const FFlightSimLandcoverPass& Pass = VisualScene.Landcover;
			UMaterialInstanceDynamic* LandcoverInstance =
				UMaterialInstanceDynamic::Create(LandcoverMaterial, Director);
			LandcoverInstance->SetTextureParameterValue(TEXT("ClassMap"), Pass.ClassMap);
			LandcoverInstance->SetScalarParameterValue(TEXT("OriginX"), static_cast<float>(Pass.OriginCm.X));
			LandcoverInstance->SetScalarParameterValue(TEXT("OriginY"), static_cast<float>(Pass.OriginCm.Y));
			LandcoverInstance->SetScalarParameterValue(TEXT("CellX"), static_cast<float>(Pass.CellXCm));
			LandcoverInstance->SetScalarParameterValue(TEXT("CellY"), static_cast<float>(Pass.CellYCm));
			LandcoverInstance->SetScalarParameterValue(TEXT("GridWidth"), static_cast<float>(Pass.GridWidth));
			LandcoverInstance->SetScalarParameterValue(TEXT("GridHeight"), static_cast<float>(Pass.GridHeight));
			LandcoverInstance->SetScalarParameterValue(TEXT("TerrainStencil"), static_cast<float>(LabelTerrainIntId));
			LandcoverTarget = NewObject<UTextureRenderTarget2D>();
			LandcoverTarget->RenderTargetFormat = RTF_R32f;
			LandcoverTarget->ClearColor = FLinearColor::Black;
			LandcoverTarget->bAutoGenerateMips = false;
			LandcoverTarget->InitAutoFormat(Width, Height);
			LandcoverTarget->UpdateResourceImmediate(true);
			LabelLandcover = NewObject<USceneCaptureComponent2D>(Director, TEXT("LabelLandcover"));
			LabelLandcover->TextureTarget = LandcoverTarget;
			LabelLandcover->CaptureSource = ESceneCaptureSource::SCS_FinalColorHDR;
			ConfigureLabelCapture(LabelLandcover);
			LabelLandcover->ShowFlags.SetPostProcessing(true);
			LabelLandcover->PostProcessSettings.WeightedBlendables.Array.Add(
				FWeightedBlendable(1.0f, LandcoverInstance));
			LabelLandcover->PostProcessBlendWeight = 1.0f;
			LabelLandcover->RegisterComponent();
		}
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

		// -- I6 (gap S3): the ground-truth passes ----------------------------
		// Each pass is one more AA-free capture through ConfigureLabelCapture
		// (the ID pass's route: SCS_FinalColorHDR, post-processing on, the
		// pass material as the one blendable replacing the tonemapper), into
		// a float target. Normal and base colour take RGBA16f; the velocity
		// takes RGBA32f because its offset encoding puts a one-pixel motion
		// at 0.5 + 0.0016 (1280 px wide), where a half float's step is
		// 4.9e-4 -- 0.31 px of quantisation against a 2 px verifier
		// tolerance. A missing material refuses the pass by name.
		if (bPasses)
		{
			auto LoadPassMaterial = [&](const TCHAR* Word, const TCHAR* Path,
			                            UMaterialInterface*& Material) -> bool
			{
				Material = LoadObject<UMaterialInterface>(nullptr, Path);
				if (Material == nullptr)
				{
					Error = FString::Printf(
						TEXT("labels.pass_material: -passes=%s needs the post-process material ")
						TEXT("%s (MD_PostProcess, blendable location 'Replacing the Tonemapper', ")
						TEXT("EmissiveColor = SceneTexture), which scripts/ue_create_materials.py ")
						TEXT("builds; refusing to write a %s pass from anything else"),
						Word, Path, Word);
					return false;
				}
				return true;
			};
			auto MakePassTarget = [&](ETextureRenderTargetFormat Format) -> UTextureRenderTarget2D*
			{
				UTextureRenderTarget2D* Target = NewObject<UTextureRenderTarget2D>();
				Target->RenderTargetFormat = Format;
				Target->ClearColor = FLinearColor::Black;
				Target->bAutoGenerateMips = false;
				Target->InitAutoFormat(Width, Height);
				Target->UpdateResourceImmediate(true);
				return Target;
			};
			auto MakePassCapture = [&](const TCHAR* Name, UTextureRenderTarget2D* Target,
			                           UMaterialInterface* Material) -> USceneCaptureComponent2D*
			{
				USceneCaptureComponent2D* Pass = NewObject<USceneCaptureComponent2D>(Director, Name);
				Pass->TextureTarget = Target;
				Pass->CaptureSource = ESceneCaptureSource::SCS_FinalColorHDR;
				ConfigureLabelCapture(Pass);
				Pass->ShowFlags.SetPostProcessing(true);
				Pass->PostProcessSettings.WeightedBlendables.Array.Add(
					FWeightedBlendable(1.0f, Material));
				Pass->PostProcessBlendWeight = 1.0f;
				Pass->RegisterComponent();
				return Pass;
			};
			if (bPassNormal)
			{
				if (!LoadPassMaterial(TEXT("normal"), RenderPassNormalMaterialPath, PassNormalMaterial))
				{
					return Fail(Error);
				}
				PassNormalTarget = MakePassTarget(RTF_RGBA16f);
				PassNormal = MakePassCapture(TEXT("PassWorldNormal"), PassNormalTarget, PassNormalMaterial);
			}
			if (bPassVelocity)
			{
				if (!LoadPassMaterial(TEXT("velocity"), RenderPassVelocityMaterialPath, PassVelocityMaterial))
				{
					return Fail(Error);
				}
				PassVelocityTarget = MakePassTarget(RTF_RGBA32f);
				PassVelocity = MakePassCapture(TEXT("PassVelocity"), PassVelocityTarget, PassVelocityMaterial);
				// The velocity is a DIFFERENCE against the previous frame, so
				// this one capture keeps its view state (the previous view
				// matrices live in it); every other label capture drops it.
				PassVelocity->bAlwaysPersistRenderingState = true;
				// Static geometry writes no velocity by default (the camera's
				// own motion over it is reconstructed from depth elsewhere and
				// is not in the buffer); force every primitive to write one so
				// the terrain's flow is in the file too.
				if (IConsoleVariable* Force = IConsoleManager::Get().FindConsoleVariable(TEXT("r.Velocity.ForceOutput")))
				{
					Force->Set(1, ECVF_SetByCode);
				}
				else
				{
					UE_LOG(LogFlightSimRender, Warning,
					       TEXT("passes: console variable r.Velocity.ForceOutput not found in this build; ")
					       TEXT("static geometry may carry zero flow"));
				}
			}
			if (bPassAlbedo)
			{
				if (!LoadPassMaterial(TEXT("albedo"), RenderPassBaseColorMaterialPath, PassAlbedoMaterial))
				{
					return Fail(Error);
				}
				PassAlbedoTarget = MakePassTarget(RTF_RGBA16f);
				PassAlbedo = MakePassCapture(TEXT("PassBaseColor"), PassAlbedoTarget, PassAlbedoMaterial);
			}
			UE_LOG(LogFlightSimRender, Display,
			       TEXT("passes: normal %s, velocity %s, albedo %s -- each an AA-free capture ")
			       TEXT("through the ID pass's route; frame_NNNN_normal.png, _flow.f32, _albedo.png"),
			       bPassNormal ? TEXT("on") : TEXT("off"), bPassVelocity ? TEXT("on") : TEXT("off"),
			       bPassAlbedo ? TEXT("on") : TEXT("off"));
		}

		// -- S4: the linear passes and the velocity cross-check -------------
		// Each is one more AA-free capture through ConfigureLabelCapture.
		// SCS_Normal / SCS_BaseColor are the engine's own GBuffer capture
		// sources (deferred renderer): no post-process material stands
		// between the GBuffer and the RTF_RGBA16f target, so the .f32 files
		// and the I6 PNGs (kept) are two routes to one quantity. A half
		// float resolves a unit normal to 5e-4 (0.03 deg), far inside the
		// verifier's 10 deg.
		auto MakeLinearPassTarget = [&](ETextureRenderTargetFormat Format) -> UTextureRenderTarget2D*
		{
			UTextureRenderTarget2D* Target = NewObject<UTextureRenderTarget2D>();
			Target->RenderTargetFormat = Format;
			Target->ClearColor = FLinearColor::Black;
			Target->bAutoGenerateMips = false;
			Target->InitAutoFormat(Width, Height);
			Target->UpdateResourceImmediate(true);
			return Target;
		};
		auto MakeNormalCapture = [&](const TCHAR* Name, UTextureRenderTarget2D* Target) -> USceneCaptureComponent2D*
		{
			USceneCaptureComponent2D* Normal = NewObject<USceneCaptureComponent2D>(Director, Name);
			Normal->TextureTarget = Target;
			Normal->CaptureSource = ESceneCaptureSource::SCS_Normal;
			ConfigureLabelCapture(Normal);
			Normal->RegisterComponent();
			return Normal;
		};
		auto MakeBaseColorCapture = [&](const TCHAR* Name, UTextureRenderTarget2D* Target) -> USceneCaptureComponent2D*
		{
			USceneCaptureComponent2D* BaseColor = NewObject<USceneCaptureComponent2D>(Director, Name);
			BaseColor->TextureTarget = Target;
			BaseColor->CaptureSource = ESceneCaptureSource::SCS_BaseColor;
			ConfigureLabelCapture(BaseColor);
			BaseColor->RegisterComponent();
			return BaseColor;
		};
		auto MakeMaterialCapture = [&](const TCHAR* Name, UTextureRenderTarget2D* Target,
		                               UMaterialInterface* Material) -> USceneCaptureComponent2D*
		{
			USceneCaptureComponent2D* Pass = NewObject<USceneCaptureComponent2D>(Director, Name);
			Pass->TextureTarget = Target;
			Pass->CaptureSource = ESceneCaptureSource::SCS_FinalColorHDR;
			ConfigureLabelCapture(Pass);
			Pass->ShowFlags.SetPostProcessing(true);
			Pass->PostProcessSettings.WeightedBlendables.Array.Add(FWeightedBlendable(1.0f, Material));
			Pass->PostProcessBlendWeight = 1.0f;
			Pass->RegisterComponent();
			return Pass;
		};
		if (bPassNormal)
		{
			LinearNormalTarget = MakeLinearPassTarget(RTF_RGBA16f);
			if (NormalSource == TEXT("material"))
			{
				UMaterialInterface* Fallback =
					LoadObject<UMaterialInterface>(nullptr, RenderWorldNormalFallbackMaterialPath);
				if (Fallback == nullptr)
				{
					return Fail(FString::Printf(
						TEXT("labels.pass_material: -normal-source=material needs the post-process ")
						TEXT("material %s (SceneTexture:WorldNormal into emissive, unencoded), which ")
						TEXT("scripts/ue_create_materials.py builds"), RenderWorldNormalFallbackMaterialPath));
				}
				LinearNormal = MakeMaterialCapture(TEXT("LinearNormalMaterial"), LinearNormalTarget, Fallback);
				LinearNormalSource = RenderWorldNormalFallbackMaterialPath;
			}
			else
			{
				LinearNormal = MakeNormalCapture(TEXT("LinearNormal"), LinearNormalTarget);
				LinearNormalSource = TEXT("SCS_Normal");
			}
		}
		if (bPassAlbedo)
		{
			LinearBaseColorTarget = MakeLinearPassTarget(RTF_RGBA16f);
			LinearBaseColor = MakeBaseColorCapture(TEXT("LinearBaseColor"), LinearBaseColorTarget);
		}
		if (bVelocityCheck)
		{
			UMaterialInterface* VelocityMaterial =
				LoadObject<UMaterialInterface>(nullptr, RenderVelocityCheckMaterialPath);
			if (VelocityMaterial == nullptr)
			{
				return Fail(FString::Printf(
					TEXT("labels.pass_material: -velocity-check needs the post-process material %s ")
					TEXT("(SceneTexture:Velocity into emissive, signed, unencoded), which ")
					TEXT("scripts/ue_create_materials.py builds"), RenderVelocityCheckMaterialPath));
			}
			// RGBA32f like the I6 velocity target, so the two routes differ
			// in the encoding only (this one signed and unencoded: whether a
			// negative emissive survives the FinalColorHDR readback is what
			// its negative_raw_values count measures on the box).
			VelocityCheckTarget = MakeLinearPassTarget(RTF_RGBA32f);
			VelocityCheck = MakeMaterialCapture(TEXT("VelocityCheck"), VelocityCheckTarget, VelocityMaterial);
			// The velocity is a DIFFERENCE against the previous frame: this
			// capture keeps its view state (the previous view matrices).
			VelocityCheck->bAlwaysPersistRenderingState = true;
			if (IConsoleVariable* Force = IConsoleManager::Get().FindConsoleVariable(TEXT("r.Velocity.ForceOutput")))
			{
				Force->Set(1, ECVF_SetByCode);
			}
		}
		if (LinearNormal != nullptr || LinearBaseColor != nullptr || VelocityCheck != nullptr)
		{
			UE_LOG(LogFlightSimRender, Display,
			       TEXT("linear passes: normal %s, base colour %s, velocity check %s -- AA-free; ")
			       TEXT("frame_NNNN_normal.f32, _basecolor.f32, _velocity.f32"),
			       LinearNormal != nullptr ? *LinearNormalSource : TEXT("off"),
			       LinearBaseColor != nullptr ? TEXT("SCS_BaseColor") : TEXT("off"),
			       VelocityCheck != nullptr ? TEXT("M_Velocity") : TEXT("off"));
		}
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

	// -- S4: the accumulation capture (-accumulate=K) ----------------------
	// A dedicated capture with the beauty's exposure and show flags but NO
	// anti-aliasing, no temporal AA and no motion blur: the K sub-exposures
	// ARE the motion blur (Haeberli & Akeley 1990, a box filter over the
	// shutter), and a temporal filter would blend them a second time. It
	// keeps its rendering state (Lumen's and the exposure's histories; no
	// pixel history, AA being off). The mean of the K linear sub-exposures
	// is written as frame_NNNN_linear.exr -- the file the Python sensor
	// post-pass reads -- and the record's accumulation{} says so, so
	// core/capture/blur.py records the engine's accumulation instead of
	// blurring a second time.
	UTextureRenderTarget2D* AccumulateTarget = nullptr;
	USceneCaptureComponent2D* AccumulateCapture = nullptr;
	TArray<AActor*> AccumulateMovers;
	TArray<FTransform> AccumulatePrevious;
	if (bAccumulate)
	{
		AccumulateTarget = NewObject<UTextureRenderTarget2D>();
		AccumulateTarget->RenderTargetFormat = RTF_RGBA32f;
		AccumulateTarget->ClearColor = FLinearColor::Black;
		AccumulateTarget->bAutoGenerateMips = false;
		AccumulateTarget->InitAutoFormat(Width, Height);
		AccumulateTarget->UpdateResourceImmediate(true);
		AccumulateCapture = NewObject<USceneCaptureComponent2D>(Director, TEXT("AccumulateCapture"));
		AccumulateCapture->SetupAttachment(Director->Camera);
		AccumulateCapture->SetMobility(EComponentMobility::Movable);
		AccumulateCapture->TextureTarget = AccumulateTarget;
		AccumulateCapture->CaptureSource = ESceneCaptureSource::SCS_FinalColorHDR;
		AccumulateCapture->bCaptureEveryFrame = false;
		AccumulateCapture->bCaptureOnMovement = false;
		AccumulateCapture->bAlwaysPersistRenderingState = true;
		AccumulateCapture->FOVAngle = Capture->FOVAngle;
		AccumulateCapture->ShowFlags = Capture->ShowFlags;
		AccumulateCapture->ShowFlags.SetAntiAliasing(false);
		AccumulateCapture->ShowFlags.SetTemporalAA(false);
		AccumulateCapture->ShowFlags.SetMotionBlur(false);
		AccumulateCapture->PostProcessSettings = Capture->PostProcessSettings;
		AccumulateCapture->PostProcessBlendWeight = Capture->PostProcessBlendWeight;
		AccumulateCapture->HiddenActors = Capture->HiddenActors;
		AccumulateCapture->RegisterComponent();
		// What moves within a window: every aircraft, and a preset camera
		// (which the world tick moves every step). A consume-poses camera
		// is placed by its solved track at each sub-exposure's instant.
		AccumulateMovers.Add(Scenario.Aircraft);
		for (AActor* Traffic : Scenario.TrafficActors)
		{
			if (Traffic != nullptr)
			{
				AccumulateMovers.Add(Traffic);
			}
		}
		if (!bConsumePoses)
		{
			AccumulateMovers.Add(Director);
		}
		UE_LOG(LogFlightSimRender, Display,
		       TEXT("accumulate: up to %d AA-off sub-exposures over the %.6f s shutter per frame ")
		       TEXT("(k = 1 below %.2f px of predicted blur); frame_NNNN_linear.exr is their mean"),
		       AccumulateRequested, ExposureShutterSeconds, RenderSubPixelBlurPx);
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
	// The physical sky takes more: Lumen's radiance cache, the temporal AA
	// history and the virtual shadow map pages all converge over frames,
	// and a first kept frame mid-convergence would flicker into the clip.
	if (bPhysicalSky)
	{
		WarmupCaptures = FMath::Max(WarmupCaptures, 16);
	}
	for (int32 i = 0; i < WarmupCaptures; ++i)
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
	// I6: the flow of a frame is from the previous CAPTURED frame of this
	// pass; the first one has no previous and writes zeros, saying so.
	bool bFlowHasPrevious = false;

	// S4: the velocity cross-check's first captured frame has no previous
	// one and writes zeros, saying so (the I6 flow's rule).
	bool bVelocityCheckHasPrevious = false;
	for (int32 Step = 0; Step < Steps; ++Step)
	{
		const double Time = Step * DeltaSeconds;
		// S4: -accumulate extrapolates each moving actor over the exposure
		// window from its motion across the last FDM step, so the pose
		// before this step is kept.
		if (AccumulateCapture != nullptr)
		{
			AccumulatePrevious.Reset();
			for (AActor* Mover : AccumulateMovers)
			{
				AccumulatePrevious.Add(Mover->GetActorTransform());
			}
		}
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
		// W5: the world look per tick at the FDM's own time -- the cloud
		// material's drift offset and the rain phase -- before any capture of
		// this step (deterministic in the step: Gate 10-R).
		if (bVisual)
		{
			VisualScene.AdvanceWorld(Scenario.ReadProperty(TEXT("simulation/sim-time-sec")));
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
		// I6: the velocity pass renders FIRST after the step, before the
		// beauty capture. Engine source reading (FScene velocity data): a
		// primitive's previous transform is kept only for the first scene
		// render after its transform changed; the next render resets
		// previous = current and its motion vector reads zero. Every other
		// pass therefore runs after the beauty capture and this one cannot.
		// What is NOT claimed: that the beauty frame rendered after this
		// extra scene render is byte-identical to one rendered without
		// -passes=velocity (Gate 10-R compares like with like), and that
		// the vector's time base is the previous CAPTURED frame rather than
		// the previous scene render -- the verifier's flow_vs_motion grades
		// that on the first Windows bundle.
		TArray<FLinearColor> VelocityRaw;
		if (PassVelocity != nullptr)
		{
			PassVelocity->FOVAngle = Capture->FOVAngle;
			PassVelocity->CaptureScene();
			FlushRenderingCommands();
			FTextureRenderTargetResource* VelocityResource =
				PassVelocityTarget->GameThread_GetRenderTargetResource();
			if (VelocityResource == nullptr
			    || !VelocityResource->ReadLinearColorPixels(
			           VelocityRaw, FReadSurfaceDataFlags(RCM_MinMax, CubeFace_MAX))
			    || VelocityRaw.Num() != Width * Height)
			{
				return Fail(TEXT("passes: could not read the velocity pass back"));
			}
		}
		// S4: the velocity cross-check renders here for the same reason (the
		// first scene render after the step); it and -passes=velocity are
		// exclusive (refused labels.velocity_check above).
		TArray<FLinearColor> VelocityCheckRaw;
		if (VelocityCheck != nullptr)
		{
			VelocityCheck->FOVAngle = Capture->FOVAngle;
			VelocityCheck->CaptureScene();
			FlushRenderingCommands();
			FTextureRenderTargetResource* CheckResource =
				VelocityCheckTarget->GameThread_GetRenderTargetResource();
			if (CheckResource == nullptr
			    || !CheckResource->ReadLinearColorPixels(
			           VelocityCheckRaw, FReadSurfaceDataFlags(RCM_MinMax, CubeFace_MAX))
			    || VelocityCheckRaw.Num() != Width * Height)
			{
				return Fail(TEXT("linear passes: could not read the velocity cross-check back"));
			}
		}
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
		// S4: this frame's metric depth (+inf for sky), handed from the label
		// bundle to the linear passes, which write 0, 0, 0 where it is sky.
		TArray<float> LabelDepthThisFrame;
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
			// W5: the land-cover ID pass -- the WorldCover code per pixel of
			// terrain (0 for sky and every non-terrain id), 8-bit, AA-free,
			// read back as raw floats like the ID pass; a non-integer value is
			// a measurement (a blend or a resample), counted, never hidden.
			if (LabelLandcover != nullptr)
			{
				LabelLandcover->FOVAngle = Capture->FOVAngle;
				TArray<FLinearColor> LandcoverRaw;
				LabelLandcover->CaptureScene();
				FlushRenderingCommands();
				FTextureRenderTargetResource* LandcoverResource =
					LandcoverTarget->GameThread_GetRenderTargetResource();
				if (LandcoverResource == nullptr
				    || !LandcoverResource->ReadLinearColorPixels(LandcoverRaw, RawFloats)
				    || LandcoverRaw.Num() != Count)
				{
					return Fail(TEXT("labels.landcover_pass: could not read the land-cover ID pass back"));
				}
				TArray<uint8> LandcoverCodes;
				LandcoverCodes.SetNumZeroed(Count);
				int32 LandcoverNonInteger = 0;
				TMap<int32, int32> LandcoverCounts;
				for (int32 i = 0; i < Count; ++i)
				{
					const float Value = LandcoverRaw[i].R;
					const int32 Code = FMath::Clamp(FMath::RoundToInt(Value), 0, 255);
					if (FMath::Abs(Value - static_cast<float>(Code)) > 1.0e-3f)
					{
						++LandcoverNonInteger;
					}
					LandcoverCodes[i] = static_cast<uint8>(Code);
					if (Code != 0)
					{
						LandcoverCounts.FindOrAdd(Code)++;
					}
				}
				// Not the Python image's name (<stem>_landcover.png, core/
				// capture/labels.py): the engine's pass sits beside it.
				const FString LandcoverName = Stem + TEXT("_landcover_id.png");
				if (!RenderWriteGrayPng(FPaths::Combine(OutputDirectory, LandcoverName),
				                        LandcoverCodes.GetData(), LandcoverCodes.Num(), Width, Height, 8))
				{
					return Fail(FString::Printf(TEXT("labels.landcover_pass: could not write %s"),
					                            *LandcoverName));
				}
				TSharedPtr<FJsonObject> CodeCounts = MakeShared<FJsonObject>();
				for (const TPair<int32, int32>& Pair : LandcoverCounts)
				{
					CodeCounts->SetNumberField(FString::FromInt(Pair.Key), Pair.Value);
				}
				Labels->SetStringField(TEXT("landcover_png"), LandcoverName);
				Labels->SetObjectField(TEXT("landcover_codes"), CodeCounts);
				Labels->SetNumberField(TEXT("landcover_non_integer_pixels"), LandcoverNonInteger);
			}
			Record->SetObjectField(TEXT("labels"), Labels);
			LabelDepthThisFrame = MoveTemp(DepthMetres);
		}
		// S4: under -accumulate the frame's linear file is the accumulation
		// (written below), so the instantaneous one is not written over it.
		if (bLinear && AccumulateCapture == nullptr)
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
		// -- I6 (gap S3): the ground-truth passes, written beside the frame --
		// Record keys normal_png / flow_f32 / albedo_png are null when the
		// pass is off, so a reader never infers a file from a name.
		if (bPasses)
		{
			const int32 PassCount = Width * Height;
			const FString PassStem = FrameName.LeftChop(4);
			auto ReadPass = [&](USceneCaptureComponent2D* Pass, UTextureRenderTarget2D* Target,
			                    const TCHAR* Word, TArray<FLinearColor>& Out) -> bool
			{
				Pass->FOVAngle = Capture->FOVAngle;
				Pass->CaptureScene();
				FlushRenderingCommands();
				FTextureRenderTargetResource* PassResource = Target->GameThread_GetRenderTargetResource();
				if (PassResource == nullptr
				    || !PassResource->ReadLinearColorPixels(
				           Out, FReadSurfaceDataFlags(RCM_MinMax, CubeFace_MAX))
				    || Out.Num() != PassCount)
				{
					Error = FString::Printf(TEXT("passes: could not read the %s pass back"), Word);
					return false;
				}
				return true;
			};
			auto Png16 = [](double Value) -> uint16
			{
				return static_cast<uint16>(FMath::Clamp(
					FMath::RoundToInt(Value * RenderPassPngMax), 0, 65535));
			};

			if (PassNormal != nullptr)
			{
				TArray<FLinearColor> Raw;
				if (!ReadPass(PassNormal, PassNormalTarget, TEXT("normal"), Raw))
				{
					return Fail(Error);
				}
				// The GBuffer normal is in ENGINE world axes; the file is in
				// the scene frame the manifest speaks (north, east, up), so
				// the verifier rotates it by the camera axes it already has.
				// The ENU vectors are taken once per frame at the camera: over
				// a frame's extent they turn by hundredths of a degree, far
				// inside the 10 deg the verifier grades at. Sky pixels carry
				// whatever the cleared GBuffer decodes to and are not claimed;
				// the depth file says where the sky is.
				FVector East, North, Up;
				Scenario.GeoReferencing->GetENUVectorsAtEngineLocation(
					Director->GetActorLocation(), East, North, Up);
				TArray<uint16> Rgba;
				Rgba.SetNumUninitialized(PassCount * 4);
				int32 UnitPixels = 0;
				for (int32 i = 0; i < PassCount; ++i)
				{
					const FVector Engine(
						(Raw[i].R - RenderPassSignedOffset) / RenderPassSignedScale,
						(Raw[i].G - RenderPassSignedOffset) / RenderPassSignedScale,
						(Raw[i].B - RenderPassSignedOffset) / RenderPassSignedScale);
					const FVector Scene(FVector::DotProduct(Engine, North),
					                    FVector::DotProduct(Engine, East),
					                    FVector::DotProduct(Engine, Up));
					const double Length = Scene.Size();
					if (FMath::Abs(Length - 1.0) < 0.05)
					{
						++UnitPixels;
					}
					const FVector N = Length > 1.0e-6 ? Scene / Length : FVector::ZeroVector;
					Rgba[4 * i + 0] = Png16(N.X * RenderPassNormalEncodeScale + RenderPassNormalEncodeOffset);
					Rgba[4 * i + 1] = Png16(N.Y * RenderPassNormalEncodeScale + RenderPassNormalEncodeOffset);
					Rgba[4 * i + 2] = Png16(N.Z * RenderPassNormalEncodeScale + RenderPassNormalEncodeOffset);
					Rgba[4 * i + 3] = 65535;
				}
				const FString NormalName = PassStem + TEXT("_normal.png");
				if (!RenderWriteRgba16Png(FPaths::Combine(OutputDirectory, NormalName), Rgba, Width, Height))
				{
					return Fail(FString::Printf(TEXT("passes: could not write %s"), *NormalName));
				}
				Record->SetStringField(TEXT("normal_png"), NormalName);
				Record->SetNumberField(TEXT("normal_unit_pixels"), UnitPixels);
			}
			else
			{
				Record->SetField(TEXT("normal_png"), MakeShared<FJsonValueNull>());
			}

			if (PassVelocity != nullptr)
			{
				// Decoded clip-space delta (x right, y UP, [-1, 1] across the
				// image) from the previous frame to this one, at this pixel;
				// screen +y is down, hence the sign on dy. Verified on Windows
				// by the verifier's flow_vs_motion, not here.
				TArray<float> Flow;
				Flow.SetNumZeroed(PassCount * 2);
				int32 MovingPixels = 0;
				if (bFlowHasPrevious)
				{
					for (int32 i = 0; i < PassCount; ++i)
					{
						const float NdcX = (VelocityRaw[i].R - RenderPassSignedOffset) / RenderPassSignedScale;
						const float NdcY = (VelocityRaw[i].G - RenderPassSignedOffset) / RenderPassSignedScale;
						const float DxPx = NdcX * 0.5f * Width;
						const float DyPx = -NdcY * 0.5f * Height;
						Flow[2 * i + 0] = DxPx;
						Flow[2 * i + 1] = DyPx;
						if (FMath::Abs(DxPx) > 0.01f || FMath::Abs(DyPx) > 0.01f)
						{
							++MovingPixels;
						}
					}
				}
				const FString FlowName = PassStem + TEXT("_flow.f32");
				TArray64<uint8> FlowBytes;
				FlowBytes.SetNumUninitialized(static_cast<int64>(Flow.Num()) * sizeof(float));
				FMemory::Memcpy(FlowBytes.GetData(), Flow.GetData(), FlowBytes.Num());
				if (!FFileHelper::SaveArrayToFile(FlowBytes, *FPaths::Combine(OutputDirectory, FlowName)))
				{
					return Fail(FString::Printf(TEXT("passes: could not write %s"), *FlowName));
				}
				Record->SetStringField(TEXT("flow_f32"), FlowName);
				Record->SetBoolField(TEXT("flow_first_frame"), !bFlowHasPrevious);
				Record->SetNumberField(TEXT("flow_moving_pixels"), MovingPixels);
				bFlowHasPrevious = true;
			}
			else
			{
				Record->SetField(TEXT("flow_f32"), MakeShared<FJsonValueNull>());
			}

			if (PassAlbedo != nullptr)
			{
				TArray<FLinearColor> Raw;
				if (!ReadPass(PassAlbedo, PassAlbedoTarget, TEXT("albedo"), Raw))
				{
					return Fail(Error);
				}
				TArray<uint16> Rgba;
				Rgba.SetNumUninitialized(PassCount * 4);
				int32 ClampedPixels = 0;
				for (int32 i = 0; i < PassCount; ++i)
				{
					const FLinearColor& C = Raw[i];
					if (C.R < 0.0f || C.R > 1.0f || C.G < 0.0f || C.G > 1.0f || C.B < 0.0f || C.B > 1.0f)
					{
						++ClampedPixels;
					}
					Rgba[4 * i + 0] = Png16(FMath::Clamp(C.R, 0.0f, 1.0f));
					Rgba[4 * i + 1] = Png16(FMath::Clamp(C.G, 0.0f, 1.0f));
					Rgba[4 * i + 2] = Png16(FMath::Clamp(C.B, 0.0f, 1.0f));
					Rgba[4 * i + 3] = 65535;
				}
				const FString AlbedoName = PassStem + TEXT("_albedo.png");
				if (!RenderWriteRgba16Png(FPaths::Combine(OutputDirectory, AlbedoName), Rgba, Width, Height))
				{
					return Fail(FString::Printf(TEXT("passes: could not write %s"), *AlbedoName));
				}
				Record->SetStringField(TEXT("albedo_png"), AlbedoName);
				Record->SetNumberField(TEXT("albedo_clamped_pixels"), ClampedPixels);
			}
			else
			{
				Record->SetField(TEXT("albedo_png"), MakeShared<FJsonValueNull>());
			}
		}
		// -- S4: the linear passes and the velocity cross-check, per frame --
		// Named twice on the record: the frame-level normal_f32 /
		// basecolor_f32 / velocity_f32 (the keys core/capture/passes.py
		// reads) and labels.normal / labels.basecolor / labels.velocity with
		// the axes and the MEASURED encoding (the keys core/capture/verify.py
		// grades when present).
		if (LinearNormal != nullptr || LinearBaseColor != nullptr || VelocityCheck != nullptr)
		{
			const int32 PixelCount = Width * Height;
			const FString LinearStem = FrameName.LeftChop(4);
			const TSharedPtr<FJsonObject>* LabelsField = nullptr;
			if (!Record->TryGetObjectField(TEXT("labels"), LabelsField) || LabelsField == nullptr
			    || !LabelsField->IsValid())
			{
				return Fail(TEXT("linear passes: the frame record carries no labels block to name them in"));
			}
			const TSharedPtr<FJsonObject> FrameLabels = *LabelsField;
			// Sky is where the label bundle's float depth is +inf.
			auto IsSky = [&](int32 i) -> bool
			{
				return LabelDepthThisFrame.Num() == PixelCount && !FMath::IsFinite(LabelDepthThisFrame[i]);
			};
			auto ReadLinearPass = [&](USceneCaptureComponent2D* Pass, UTextureRenderTarget2D* Target,
			                          const TCHAR* Word, TArray<FLinearColor>& Out) -> bool
			{
				Pass->FOVAngle = Capture->FOVAngle;
				Pass->CaptureScene();
				FlushRenderingCommands();
				FTextureRenderTargetResource* PassResource = Target->GameThread_GetRenderTargetResource();
				if (PassResource == nullptr
				    || !PassResource->ReadLinearColorPixels(
				           Out, FReadSurfaceDataFlags(RCM_MinMax, CubeFace_MAX))
				    || Out.Num() != PixelCount)
				{
					Error = FString::Printf(TEXT("linear passes: could not read the %s capture back"), Word);
					return false;
				}
				return true;
			};

			if (LinearNormal != nullptr)
			{
				TArray<FLinearColor> Raw;
				if (!ReadLinearPass(LinearNormal, LinearNormalTarget, TEXT("normal"), Raw))
				{
					return Fail(Error);
				}
				// The encoding, measured on the geometry pixels: which decode
				// gives unit vectors -- the texel itself ("signed") or
				// (texel - 0.5) / 0.5 ("offset_half")?
				int32 GeometryPixels = 0, UnitSigned = 0, UnitOffset = 0;
				for (int32 i = 0; i < PixelCount; ++i)
				{
					if (IsSky(i))
					{
						continue;
					}
					++GeometryPixels;
					const FVector Texel(Raw[i].R, Raw[i].G, Raw[i].B);
					const FVector Offset = (Texel - FVector(RenderPassSignedOffset)) / RenderPassSignedScale;
					if (FMath::Abs(Texel.Size() - 1.0) < RenderNormalUnitTolerance)
					{
						++UnitSigned;
					}
					if (FMath::Abs(Offset.Size() - 1.0) < RenderNormalUnitTolerance)
					{
						++UnitOffset;
					}
				}
				const double FractionSigned = GeometryPixels > 0 ? double(UnitSigned) / GeometryPixels : 0.0;
				const double FractionOffset = GeometryPixels > 0 ? double(UnitOffset) / GeometryPixels : 0.0;
				FString Encoding = TEXT("undetermined (no geometry pixels)");
				if (GeometryPixels > 0)
				{
					if (FractionSigned >= RenderNormalUnitFraction && FractionSigned >= FractionOffset)
					{
						Encoding = TEXT("signed");
					}
					else if (FractionOffset >= RenderNormalUnitFraction)
					{
						Encoding = TEXT("offset_half");
					}
					else
					{
						return Fail(FString::Printf(
							TEXT("labels.normal_encoding: the %s normals of %s decode to unit length on ")
							TEXT("%.1f %% of %d geometry pixels read as signed and %.1f %% read as ")
							TEXT("n * 0.5 + 0.5; neither is the encoding (render with ")
							TEXT("-normal-source=material, the M_WorldNormal fallback)"),
							*LinearNormalSource, *FrameName, 100.0 * FractionSigned, GeometryPixels,
							100.0 * FractionOffset));
					}
				}
				// Engine world axes -> the scene frame (north, east, up), by the
				// ENU vectors at the camera (the I6 normal PNG's rotation).
				FVector EastAxis, NorthAxis, UpAxis;
				Scenario.GeoReferencing->GetENUVectorsAtEngineLocation(
					Director->GetActorLocation(), EastAxis, NorthAxis, UpAxis);
				const bool bOffsetEncoded = Encoding == TEXT("offset_half");
				TArray<float> Normal;
				Normal.SetNumZeroed(PixelCount * RenderLinearChannels);
				int32 UnitPixels = 0;
				for (int32 i = 0; i < PixelCount && GeometryPixels > 0; ++i)
				{
					if (IsSky(i))
					{
						continue;   // 0, 0, 0: the depth file says where the sky is
					}
					FVector Engine(Raw[i].R, Raw[i].G, Raw[i].B);
					if (bOffsetEncoded)
					{
						Engine = (Engine - FVector(RenderPassSignedOffset)) / RenderPassSignedScale;
					}
					const FVector Scene(FVector::DotProduct(Engine, NorthAxis),
					                    FVector::DotProduct(Engine, EastAxis),
					                    FVector::DotProduct(Engine, UpAxis));
					const double Length = Scene.Size();
					if (FMath::Abs(Length - 1.0) < RenderNormalUnitTolerance)
					{
						++UnitPixels;
					}
					const FVector N = Length > 1.0e-6 ? Scene / Length : FVector::ZeroVector;
					Normal[RenderLinearChannels * i + 0] = static_cast<float>(N.X);
					Normal[RenderLinearChannels * i + 1] = static_cast<float>(N.Y);
					Normal[RenderLinearChannels * i + 2] = static_cast<float>(N.Z);
				}
				const FString NormalName = LinearStem + TEXT("_normal.f32");
				if (!WriteLinearF32(FPaths::Combine(OutputDirectory, NormalName), Normal, Width, Height,
				                    RenderLinearChannels))
				{
					return Fail(FString::Printf(TEXT("linear passes: could not write %s"), *NormalName));
				}
				Record->SetStringField(TEXT("normal_f32"), NormalName);
				FrameLabels->SetStringField(TEXT("normal"), NormalName);
				FrameLabels->SetStringField(TEXT("normal_axes"), RenderNormalAxes);
				FrameLabels->SetStringField(TEXT("normal_encoding"), Encoding);
				TSharedPtr<FJsonObject> Evidence = MakeShared<FJsonObject>();
				Evidence->SetStringField(TEXT("source"), LinearNormalSource);
				Evidence->SetNumberField(TEXT("geometry_pixels"), GeometryPixels);
				Evidence->SetNumberField(TEXT("unit_fraction_signed"), FractionSigned);
				Evidence->SetNumberField(TEXT("unit_fraction_offset_half"), FractionOffset);
				Evidence->SetNumberField(TEXT("unit_pixels"), UnitPixels);
				FrameLabels->SetObjectField(TEXT("normal_encoding_evidence"), Evidence);
			}

			if (LinearBaseColor != nullptr)
			{
				TArray<FLinearColor> Raw;
				if (!ReadLinearPass(LinearBaseColor, LinearBaseColorTarget, TEXT("base colour"), Raw))
				{
					return Fail(Error);
				}
				TArray<float> BaseColor;
				BaseColor.SetNumZeroed(PixelCount * RenderLinearChannels);
				int32 OutOfRange = 0;
				for (int32 i = 0; i < PixelCount; ++i)
				{
					if (IsSky(i))
					{
						continue;
					}
					const FLinearColor& C = Raw[i];
					if (C.R < 0.0f || C.R > 1.0f || C.G < 0.0f || C.G > 1.0f || C.B < 0.0f || C.B > 1.0f)
					{
						++OutOfRange;   // counted, never clamped: the file is what the GBuffer held
					}
					BaseColor[RenderLinearChannels * i + 0] = C.R;
					BaseColor[RenderLinearChannels * i + 1] = C.G;
					BaseColor[RenderLinearChannels * i + 2] = C.B;
				}
				const FString BaseColorName = LinearStem + TEXT("_basecolor.f32");
				if (!WriteLinearF32(FPaths::Combine(OutputDirectory, BaseColorName), BaseColor, Width, Height,
				                    RenderLinearChannels))
				{
					return Fail(FString::Printf(TEXT("linear passes: could not write %s"), *BaseColorName));
				}
				Record->SetStringField(TEXT("basecolor_f32"), BaseColorName);
				FrameLabels->SetStringField(TEXT("basecolor"), BaseColorName);
				FrameLabels->SetNumberField(TEXT("basecolor_out_of_range_pixels"), OutOfRange);
			}

			if (VelocityCheck != nullptr)
			{
				// Signed clip-space delta (x right, y UP) -> pixels, screen +y
				// down: the I6 flow's decode without its offset. A read-back
				// beside the Python flow (S2), never the truth.
				TArray<float> Velocity;
				Velocity.SetNumZeroed(PixelCount * 2);
				TArray<float> Speeds;
				int32 MovingPixels = 0, NegativeRaw = 0;
				for (int32 i = 0; i < PixelCount; ++i)
				{
					if (VelocityCheckRaw[i].R < 0.0f || VelocityCheckRaw[i].G < 0.0f)
					{
						++NegativeRaw;
					}
				}
				if (bVelocityCheckHasPrevious)
				{
					for (int32 i = 0; i < PixelCount; ++i)
					{
						const float DxPx = VelocityCheckRaw[i].R * 0.5f * Width;
						const float DyPx = -VelocityCheckRaw[i].G * 0.5f * Height;
						Velocity[2 * i + 0] = DxPx;
						Velocity[2 * i + 1] = DyPx;
						if (IsSky(i))
						{
							continue;
						}
						const float Speed = FMath::Sqrt(DxPx * DxPx + DyPx * DyPx);
						Speeds.Add(Speed);
						if (Speed > 0.01f)
						{
							++MovingPixels;
						}
					}
				}
				const double P95 = RenderPercentile95(Speeds);
				const FString VelocityName = LinearStem + TEXT("_velocity.f32");
				if (!WriteLinearF32(FPaths::Combine(OutputDirectory, VelocityName), Velocity, Width, Height, 2))
				{
					return Fail(FString::Printf(TEXT("linear passes: could not write %s"), *VelocityName));
				}
				Record->SetStringField(TEXT("velocity_f32"), VelocityName);
				TSharedPtr<FJsonObject> VelocityRecord = MakeShared<FJsonObject>();
				VelocityRecord->SetStringField(TEXT("file"), VelocityName);
				VelocityRecord->SetBoolField(TEXT("first_frame"), !bVelocityCheckHasPrevious);
				VelocityRecord->SetNumberField(TEXT("p95_px"), P95);
				VelocityRecord->SetNumberField(TEXT("moving_pixels"), MovingPixels);
				VelocityRecord->SetNumberField(TEXT("negative_raw_values"), NegativeRaw);
				VelocityRecord->SetStringField(TEXT("role"),
					TEXT("read-back: the engine's velocity beside the Python flow (S2), never the truth"));
				FrameLabels->SetObjectField(TEXT("velocity"), VelocityRecord);
				bVelocityCheckHasPrevious = true;
			}
		}
		// -- S4: the accumulation (-accumulate=K) ---------------------------
		// The window is the card's shutter CENTRED on the capture instant
		// (core/capture/blur.py's symmetric window): [t - t_exp / 2,
		// t + t_exp / 2]. Every mover is placed at a sub-exposure's instant
		// by LINEAR extrapolation of its motion over the last FDM step
		// (translation, and rotation at that step's constant angular rate --
		// blur.py's linear-motion model); a consume-poses camera by its
		// solved track. The predicted blur (the primary's origin and a static
		// point 1 km down the axis, between the window's two ends) sets k:
		// 1 under 0.25 px, else the K asked for. Everything is put back
		// before the rest of the frame is recorded.
		if (AccumulateCapture != nullptr)
		{
			const double Now = Scenario.ReadProperty(TEXT("simulation/sim-time-sec"));
			const double Shutter = ExposureShutterSeconds;
			const double WindowStart = Now - 0.5 * Shutter;
			const double WindowEnd = Now + 0.5 * Shutter;
			TArray<FTransform> AtCapture;
			for (AActor* Mover : AccumulateMovers)
			{
				AtCapture.Add(Mover->GetActorTransform());
			}
			const bool bHavePrevious = AccumulatePrevious.Num() == AccumulateMovers.Num();
			int32 CameraHeld = 0;
			auto PlaceAt = [&](double Offset)
			{
				const double Fraction = Offset / DeltaSeconds;
				for (int32 m = 0; m < AccumulateMovers.Num(); ++m)
				{
					FTransform Placed = AtCapture[m];
					if (bHavePrevious)
					{
						const FTransform& Before = AccumulatePrevious[m];
						Placed.SetLocation(AtCapture[m].GetLocation()
						                   + (AtCapture[m].GetLocation() - Before.GetLocation()) * Fraction);
						const FQuat Delta = AtCapture[m].GetRotation() * Before.GetRotation().Inverse();
						FVector Axis;
						double Angle = 0.0;
						Delta.ToAxisAndAngle(Axis, Angle);
						Angle = FMath::UnwindRadians(Angle);
						Placed.SetRotation((FQuat(Axis, Angle * Fraction) * AtCapture[m].GetRotation()).GetNormalized());
					}
					AccumulateMovers[m]->SetActorTransform(Placed, false, nullptr, ETeleportType::TeleportPhysics);
				}
				AccumulateCapture->FOVAngle = Capture->FOVAngle;
				if (bConsumePoses)
				{
					FString PoseError;
					if (!Director->ApplyPoseAtTime(Now + Offset, PoseError))
					{
						// Outside the solved track (its ends): held at the
						// frame's own pose, and counted.
						Director->ApplyPoseAtTime(Now, PoseError);
						++CameraHeld;
					}
					AccumulateCapture->FOVAngle = static_cast<float>(FMath::RadiansToDegrees(
						2.0 * FMath::Atan(CameraSensorWidthMm / (2.0 * Director->GetAppliedFocalLengthMm()))));
				}
			};
			// The predicted blur between the window's ends.
			const FVector StaticProbe = AccumulateCapture->GetComponentLocation()
			                            + AccumulateCapture->GetForwardVector() * (1000.0 * RenderCmPerMetre);
			FVector2D AircraftStart, AircraftEnd, StaticStart, StaticEnd;
			PlaceAt(-0.5 * Shutter);
			const bool bAircraftStart = RenderPixelInFront(AccumulateCapture, Width, Height,
			                                               Scenario.Aircraft->GetActorLocation(), AircraftStart);
			const bool bStaticStart = RenderPixelInFront(AccumulateCapture, Width, Height, StaticProbe, StaticStart);
			PlaceAt(+0.5 * Shutter);
			const bool bAircraftEnd = RenderPixelInFront(AccumulateCapture, Width, Height,
			                                             Scenario.Aircraft->GetActorLocation(), AircraftEnd);
			const bool bStaticEnd = RenderPixelInFront(AccumulateCapture, Width, Height, StaticProbe, StaticEnd);
			double PredictedBlurPx = 0.0;
			if (bAircraftStart && bAircraftEnd)
			{
				PredictedBlurPx = FMath::Max(PredictedBlurPx, FVector2D::Distance(AircraftStart, AircraftEnd));
			}
			if (bStaticStart && bStaticEnd)
			{
				PredictedBlurPx = FMath::Max(PredictedBlurPx, FVector2D::Distance(StaticStart, StaticEnd));
			}
			const int32 SubExposures = AccumulationCount(PredictedBlurPx, AccumulateRequested);
			// K sub-exposures at the midpoints of K equal slices of the window
			// (a box filter); k = 1 is the capture instant itself.
			TArray<FLinearColor> Mean;
			Mean.SetNumZeroed(Width * Height);
			TArray<FLinearColor> Sub;
			TArray<TSharedPtr<FJsonValue>> SubTimes;
			for (int32 k = 0; k < SubExposures; ++k)
			{
				const double Offset = Shutter * ((k + 0.5) / SubExposures - 0.5);
				PlaceAt(Offset);
				World->SendAllEndOfFrameUpdates();
				FlushRenderingCommands();
				AccumulateCapture->CaptureScene();
				FlushRenderingCommands();
				FTextureRenderTargetResource* AccumulateResource =
					AccumulateTarget->GameThread_GetRenderTargetResource();
				if (AccumulateResource == nullptr
				    || !AccumulateResource->ReadLinearColorPixels(
				           Sub, FReadSurfaceDataFlags(RCM_MinMax, CubeFace_MAX))
				    || Sub.Num() != Width * Height)
				{
					return Fail(FString::Printf(TEXT("accumulate: could not read sub-exposure %d of %s back"),
					                            k, *FrameName));
				}
				for (int32 i = 0; i < Sub.Num(); ++i)
				{
					Mean[i] += Sub[i];
				}
				SubTimes.Add(MakeShared<FJsonValueNumber>(Now + Offset));
			}
			for (FLinearColor& Pixel : Mean)
			{
				Pixel /= static_cast<float>(SubExposures);
			}
			// Put everything back as it was at the capture instant.
			for (int32 m = 0; m < AccumulateMovers.Num(); ++m)
			{
				AccumulateMovers[m]->SetActorTransform(AtCapture[m], false, nullptr, ETeleportType::TeleportPhysics);
			}
			if (bConsumePoses && !Director->ApplyPoseAtTime(Now, Error))
			{
				return Fail(Error);
			}
			World->SendAllEndOfFrameUpdates();
			FlushRenderingCommands();
			IImageWrapperModule& AccumulateWrappers =
				FModuleManager::LoadModuleChecked<IImageWrapperModule>(TEXT("ImageWrapper"));
			TSharedPtr<IImageWrapper> AccumulateExr = AccumulateWrappers.CreateImageWrapper(EImageFormat::EXR);
			const FString AccumulateName = FrameName.LeftChop(4) + TEXT("_linear.exr");
			if (!AccumulateExr.IsValid()
			    || !AccumulateExr->SetRaw(Mean.GetData(), static_cast<int64>(Mean.Num()) * sizeof(FLinearColor),
			                              Width, Height, ERGBFormat::RGBAF, 32))
			{
				return Fail(TEXT("accumulate: could not encode the EXR"));
			}
			const TArray64<uint8> AccumulateBytes = AccumulateExr->GetCompressed();
			if (AccumulateBytes.Num() == 0
			    || !FFileHelper::SaveArrayToFile(AccumulateBytes, *FPaths::Combine(OutputDirectory, AccumulateName)))
			{
				return Fail(FString::Printf(TEXT("accumulate: could not write %s"), *AccumulateName));
			}
			Record->SetStringField(TEXT("linear"), AccumulateName);
			TSharedPtr<FJsonObject> Accumulation = MakeShared<FJsonObject>();
			Accumulation->SetNumberField(TEXT("k"), SubExposures);
			Accumulation->SetNumberField(TEXT("requested_k"), AccumulateRequested);
			Accumulation->SetNumberField(TEXT("t0_s"), WindowStart);
			Accumulation->SetNumberField(TEXT("t1_s"), WindowEnd);
			Accumulation->SetNumberField(TEXT("exposure_s"), Shutter);
			Accumulation->SetArrayField(TEXT("sub_frame_times_s"), SubTimes);
			Accumulation->SetNumberField(TEXT("predicted_blur_px"), PredictedBlurPx);
			Accumulation->SetStringField(TEXT("rule"),
				TEXT("k = 1 when the predicted blur is under 0.25 px (core/capture/blur.py ")
				TEXT("SUB_PIXEL_BLUR_PX), else the K asked for"));
			Accumulation->SetStringField(TEXT("file"), AccumulateName);
			Accumulation->SetStringField(TEXT("filter"),
				TEXT("box: the mean of k linear sub-exposures at the midpoints of k equal slices of ")
				TEXT("[t0_s, t1_s], each AA-free with the beauty's exposure"));
			Accumulation->SetStringField(TEXT("motion_model"),
				TEXT("each aircraft (and a preset camera) extrapolated linearly from its motion over ")
				TEXT("the last FDM step; a consume-poses camera placed by its solved track"));
			Accumulation->SetNumberField(TEXT("camera_held_sub_frames"), CameraHeld);
			Accumulation->SetStringField(TEXT("anti_aliasing"), TEXT("none"));
			Accumulation->SetStringField(TEXT("not_claimed"),
				TEXT("control-surface motion within the window, a rolling shutter, and that the beauty ")
				TEXT("PNG (instantaneous, TSR) shows this blur: the sensor post-pass reads the accumulation"));
			Record->SetObjectField(TEXT("accumulation"), Accumulation);
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

	// -- S4: the calibration frame (-calibration) ---------------------------
	// Rendered AFTER every delivered frame, so none of them changes. One
	// frame of three quads RenderCalibrationDistanceM down a camera that
	// looks WITH the light (the sun behind it: a quad facing the camera
	// faces the sun, N.L = 1), at the beauty camera's last position:
	//  * left, the emissive grey quad (M_GreyCard, Reflectance 0,
	//    Luminance = the stated grey_card_nits): measures one emissive unit
	//    = 1 cd/m^2 through the exposure;
	//  * right, the white Lambertian quad (Reflectance 0.9, Luminance 0) lit
	//    by the sun ALONE: sky light, GI, AO, reflections and fog off (show
	//    flags), the sun's atmosphere transmittance, cloud shadows and
	//    shadows off, so the stated lux reaches it;
	//  * centre, the slanted-edge quad: the emissive grey quad turned 5 deg
	//    about the view axis, against the black of nothing (only the quads
	//    render: PRM_UseShowOnlyList, atmosphere off).
	// Captured AA-free as FinalColorHDR into RTF_RGBA32f with the beauty's
	// exposure. PREDICTED from core/capture/radiometry.py's chain (this
	// file's LuminancePerUnit / LambertianLuminance, A read back), MEASURED
	// as the mean Rec. 709 luminance over each quad's inner half. The root
	// predicted / measured / ratio are the 18 % grey card's the chain
	// predicts: the white quad's measurement scaled by 0.18 / 0.9 (the
	// ratio is the white quad's own). Written: calibration_0000.png (the
	// linear frame sRGB-encoded, 8-bit, for the sensor post-pass),
	// calibration_0000_linear.f32 (WriteLinearF32, 3 channels), and
	// render.json calibration{} -- the same object as calibration.json.
	TSharedPtr<FJsonObject> Calibration;
	if (bCalibration)
	{
		UDirectionalLightComponent* CalibrationSun =
			Cast<UDirectionalLightComponent>(VisualScene.Sun->GetLightComponent());
		const FVector LightDirection = VisualScene.Sun->GetActorForwardVector();
		AActor* Rig = World->SpawnActor<AActor>();
		USceneComponent* RigRoot = NewObject<USceneComponent>(Rig, TEXT("CalibrationRoot"));
		Rig->SetRootComponent(RigRoot);
		RigRoot->SetMobility(EComponentMobility::Movable);
		RigRoot->RegisterComponent();
		Rig->SetActorLocationAndRotation(Director->Camera->GetComponentLocation(),
		                                 FRotator(LightDirection.Rotation().Pitch,
		                                          LightDirection.Rotation().Yaw, 0.0));

		UTextureRenderTarget2D* CalibrationTarget = NewObject<UTextureRenderTarget2D>();
		CalibrationTarget->RenderTargetFormat = RTF_RGBA32f;
		CalibrationTarget->ClearColor = FLinearColor::Black;
		CalibrationTarget->bAutoGenerateMips = false;
		CalibrationTarget->InitAutoFormat(Width, Height);
		CalibrationTarget->UpdateResourceImmediate(true);
		USceneCaptureComponent2D* CalibrationCapture =
			NewObject<USceneCaptureComponent2D>(Rig, TEXT("CalibrationCapture"));
		CalibrationCapture->SetupAttachment(RigRoot);
		CalibrationCapture->SetMobility(EComponentMobility::Movable);
		CalibrationCapture->TextureTarget = CalibrationTarget;
		CalibrationCapture->CaptureSource = ESceneCaptureSource::SCS_FinalColorHDR;
		CalibrationCapture->bCaptureEveryFrame = false;
		CalibrationCapture->bCaptureOnMovement = false;
		CalibrationCapture->bAlwaysPersistRenderingState = true;
		CalibrationCapture->FOVAngle = Capture->FOVAngle;
		CalibrationCapture->PostProcessSettings = Capture->PostProcessSettings;
		CalibrationCapture->PostProcessBlendWeight = Capture->PostProcessBlendWeight;
		CalibrationCapture->ShowFlags = Capture->ShowFlags;
		CalibrationCapture->ShowFlags.SetAntiAliasing(false);
		CalibrationCapture->ShowFlags.SetTemporalAA(false);
		CalibrationCapture->ShowFlags.SetFog(false);
		CalibrationCapture->ShowFlags.SetVolumetricFog(false);
		CalibrationCapture->ShowFlags.SetAtmosphere(false);
		CalibrationCapture->ShowFlags.SetCloud(false);
		CalibrationCapture->ShowFlags.SetBloom(false);
		CalibrationCapture->ShowFlags.SetMotionBlur(false);
		CalibrationCapture->ShowFlags.SetDepthOfField(false);
		CalibrationCapture->ShowFlags.SetLensFlares(false);
		CalibrationCapture->ShowFlags.SetTranslucency(false);
		CalibrationCapture->ShowFlags.SetVignette(false);
		CalibrationCapture->ShowFlags.SetSkyLighting(false);
		CalibrationCapture->ShowFlags.SetGlobalIllumination(false);
		CalibrationCapture->ShowFlags.SetLumenGlobalIllumination(false);
		CalibrationCapture->ShowFlags.SetLumenReflections(false);
		CalibrationCapture->ShowFlags.SetAmbientOcclusion(false);
		CalibrationCapture->ShowFlags.SetReflectionEnvironment(false);
		CalibrationCapture->ShowFlags.SetScreenSpaceReflections(false);
		CalibrationCapture->ShowFlags.SetDynamicShadows(false);
		CalibrationCapture->PrimitiveRenderMode = ESceneCapturePrimitiveRenderMode::PRM_UseShowOnlyList;
		CalibrationCapture->ShowOnlyActors.Add(Rig);
		CalibrationCapture->RegisterComponent();

		// The quads: /Engine/BasicShapes/Plane (100 cm a side, normal +Z),
		// turned to face the camera (local Z -> the rig's -X, local X -> up,
		// so local Y runs across the image), then rolled about the view axis.
		const double DistanceCm = RenderCalibrationDistanceM * RenderCmPerMetre;
		const double HalfWidthCm = DistanceCm * FMath::Tan(FMath::DegreesToRadians(CalibrationCapture->FOVAngle * 0.5));
		const double HalfHeightCm = HalfWidthCm * Height / double(Width);
		const double QuadCm = RenderCalibrationQuadFraction * 2.0 * HalfHeightCm;
		const double GreyCardNits = LambertianLuminance(AppliedSunLux, RenderGreyCardReflectance);
		struct FCalibrationQuad
		{
			const TCHAR* Name;
			double OffsetFraction;
			double RollDeg;
			double Luminance;
			double Reflectance;
			UStaticMeshComponent* Mesh;
		};
		FCalibrationQuad Quads[3] = {
			{TEXT("CalibrationEmissive"), -RenderCalibrationQuadOffset, 0.0, GreyCardNits, 0.0, nullptr},
			{TEXT("CalibrationSlantedEdge"), 0.0, RenderSlantedEdgeAngleDeg, GreyCardNits, 0.0, nullptr},
			{TEXT("CalibrationWhite"), RenderCalibrationQuadOffset, 0.0, 0.0, RenderWhiteQuadReflectance, nullptr},
		};
		const FQuat Facing = FRotationMatrix::MakeFromZX(FVector(-1.0, 0.0, 0.0), FVector(0.0, 0.0, 1.0)).ToQuat();
		for (FCalibrationQuad& Quad : Quads)
		{
			UStaticMeshComponent* Mesh = NewObject<UStaticMeshComponent>(Rig, Quad.Name);
			Mesh->SetupAttachment(RigRoot);
			Mesh->SetMobility(EComponentMobility::Movable);
			Mesh->SetStaticMesh(CalibrationPlane);
			Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			Mesh->SetCastShadow(false);
			UMaterialInstanceDynamic* Instance = UMaterialInstanceDynamic::Create(CalibrationGreyCard, Rig);
			Instance->SetScalarParameterValue(FName(RenderGreyCardLuminanceParameter),
			                                  static_cast<float>(Quad.Luminance));
			Instance->SetScalarParameterValue(FName(RenderGreyCardReflectanceParameter),
			                                  static_cast<float>(Quad.Reflectance));
			Mesh->SetMaterial(0, Instance);
			Mesh->RegisterComponent();
			const FQuat Roll(FVector(1.0, 0.0, 0.0), FMath::DegreesToRadians(Quad.RollDeg));
			Mesh->SetRelativeLocationAndRotation(
				FVector(DistanceCm, Quad.OffsetFraction * HalfWidthCm, 0.0), Roll * Facing);
			Mesh->SetRelativeScale3D(FVector(QuadCm / 100.0, QuadCm / 100.0, 1.0));
			Quad.Mesh = Mesh;
		}
		// The sun alone, as stated: no atmosphere transmittance on it, no
		// cloud shadow, no shadow at all (the frame is the last render).
		CalibrationSun->SetAtmosphereSunLight(false);
		CalibrationSun->SetCastCloudShadows(false);
		CalibrationSun->SetCastShadows(false);
		World->SendAllEndOfFrameUpdates();
		FlushRenderingCommands();
		if (GShaderCompilingManager != nullptr)
		{
			GShaderCompilingManager->FinishAllCompilation();
		}
		FAssetCompilingManager::Get().FinishAllCompilation();
		// Two discarded captures (the main warm-up's measured rule: a new
		// capture resolves nothing for two calls), then the one read.
		for (int32 i = 0; i < 3; ++i)
		{
			CalibrationCapture->CaptureScene();
			FlushRenderingCommands();
		}
		TArray<FLinearColor> CalibrationLinear;
		FTextureRenderTargetResource* CalibrationResource = CalibrationTarget->GameThread_GetRenderTargetResource();
		if (CalibrationResource == nullptr
		    || !CalibrationResource->ReadLinearColorPixels(
		           CalibrationLinear, FReadSurfaceDataFlags(RCM_MinMax, CubeFace_MAX))
		    || CalibrationLinear.Num() != Width * Height)
		{
			return Fail(TEXT("calibration: could not read the calibration frame back"));
		}
		TArray<float> CalibrationLuminance;
		CalibrationLuminance.SetNumUninitialized(Width * Height);
		for (int32 i = 0; i < CalibrationLinear.Num(); ++i)
		{
			CalibrationLuminance[i] = static_cast<float>(RenderLuminance709(CalibrationLinear[i]));
		}

		// Each quad's projected box (its four corners), and the mean over the
		// box's inner half.
		auto QuadPoint = [&](const FCalibrationQuad& Quad, double LocalX, double LocalY, FVector2D& Pixel) -> bool
		{
			return RenderPixelInFront(CalibrationCapture, Width, Height,
			                          Quad.Mesh->GetComponentTransform().TransformPosition(FVector(LocalX, LocalY, 0.0)),
			                          Pixel);
		};
		auto QuadBox = [&](const FCalibrationQuad& Quad, FVector2D& Min, FVector2D& Max) -> bool
		{
			Min = FVector2D(TNumericLimits<double>::Max(), TNumericLimits<double>::Max());
			Max = -Min;
			for (const FVector2D Corner : {FVector2D(-50.0, -50.0), FVector2D(50.0, -50.0),
			                               FVector2D(50.0, 50.0), FVector2D(-50.0, 50.0)})
			{
				FVector2D Pixel;
				if (!QuadPoint(Quad, Corner.X, Corner.Y, Pixel))
				{
					return false;
				}
				Min = FVector2D(FMath::Min(Min.X, Pixel.X), FMath::Min(Min.Y, Pixel.Y));
				Max = FVector2D(FMath::Max(Max.X, Pixel.X), FMath::Max(Max.Y, Pixel.Y));
			}
			return Min.X >= 0.0 && Min.Y >= 0.0 && Max.X <= Width && Max.Y <= Height;
		};
		auto QuadArray = [](int32 U0, int32 V0, int32 U1, int32 V1)
		{
			TArray<TSharedPtr<FJsonValue>> Corners;
			for (const FIntPoint Corner : {FIntPoint(U0, V0), FIntPoint(U1, V0), FIntPoint(U1, V1), FIntPoint(U0, V1)})
			{
				TArray<TSharedPtr<FJsonValue>> Pair;
				Pair.Add(MakeShared<FJsonValueNumber>(Corner.X));
				Pair.Add(MakeShared<FJsonValueNumber>(Corner.Y));
				Corners.Add(MakeShared<FJsonValueArray>(Pair));
			}
			return Corners;
		};
		auto MeasureQuad = [&](const FCalibrationQuad& Quad, double Predicted, TSharedPtr<FJsonObject>& Out) -> double
		{
			FVector2D Min, Max;
			if (!QuadBox(Quad, Min, Max))
			{
				return -1.0;
			}
			const double InsetU = (Max.X - Min.X) * RenderCalibrationInset;
			const double InsetV = (Max.Y - Min.Y) * RenderCalibrationInset;
			const int32 U0 = FMath::Clamp(FMath::CeilToInt(Min.X + InsetU), 0, Width);
			const int32 U1 = FMath::Clamp(FMath::FloorToInt(Max.X - InsetU), 0, Width);
			const int32 V0 = FMath::Clamp(FMath::CeilToInt(Min.Y + InsetV), 0, Height);
			const int32 V1 = FMath::Clamp(FMath::FloorToInt(Max.Y - InsetV), 0, Height);
			double Sum = 0.0, SumR = 0.0, SumG = 0.0, SumB = 0.0;
			int32 QuadPixels = 0;
			for (int32 V = V0; V < V1; ++V)
			{
				for (int32 U = U0; U < U1; ++U)
				{
					const FLinearColor& C = CalibrationLinear[V * Width + U];
					Sum += CalibrationLuminance[V * Width + U];
					SumR += C.R;
					SumG += C.G;
					SumB += C.B;
					++QuadPixels;
				}
			}
			if (QuadPixels == 0)
			{
				return -1.0;
			}
			const double Measured = Sum / QuadPixels;
			Out = MakeShared<FJsonObject>();
			Out->SetNumberField(TEXT("predicted"), Predicted);
			Out->SetNumberField(TEXT("measured"), Measured);
			Out->SetNumberField(TEXT("ratio"), Measured / Predicted);
			Out->SetNumberField(TEXT("pixels"), QuadPixels);
			Out->SetArrayField(TEXT("quad_px"), QuadArray(U0, V0, U1, V1));
			TArray<TSharedPtr<FJsonValue>> MeanRgb;
			MeanRgb.Add(MakeShared<FJsonValueNumber>(SumR / QuadPixels));
			MeanRgb.Add(MakeShared<FJsonValueNumber>(SumG / QuadPixels));
			MeanRgb.Add(MakeShared<FJsonValueNumber>(SumB / QuadPixels));
			Out->SetArrayField(TEXT("mean_rgb"), MeanRgb);
			return Measured;
		};

		// The chain, as core/capture/radiometry.py states it, with A read
		// back from the engine and EC the bias the exposure path pinned.
		double LensAttenuation = RenderLensAttenuationDefault;
		FString LensAttenuationBasis =
			TEXT("the documented default 0.78 [unverified here]: r.EyeAdaptation.LensAttenuation not found");
		if (IConsoleVariable* Attenuation = IConsoleManager::Get().FindConsoleVariable(TEXT("r.EyeAdaptation.LensAttenuation")))
		{
			LensAttenuation = Attenuation->GetFloat();
			LensAttenuationBasis = TEXT("read back from r.EyeAdaptation.LensAttenuation");
		}
		const double ExposureCompensation = Capture->PostProcessSettings.bOverride_AutoExposureBias
			? static_cast<double>(Capture->PostProcessSettings.AutoExposureBias) : 0.0;
		const double PerUnit = LuminancePerUnit(AppliedEv100, ExposureCompensation, LensAttenuation);
		const double EmissivePredicted = GreyCardNits / PerUnit;
		const double WhitePredicted = LambertianLuminance(AppliedSunLux, RenderWhiteQuadReflectance) / PerUnit;
		const double GreyPredicted = LambertianLuminance(AppliedSunLux, RenderGreyCardReflectance) / PerUnit;
		TSharedPtr<FJsonObject> EmissiveRecord, WhiteRecord;
		const double EmissiveMeasured = MeasureQuad(Quads[0], EmissivePredicted, EmissiveRecord);
		const double WhiteMeasured = MeasureQuad(Quads[2], WhitePredicted, WhiteRecord);
		if (EmissiveMeasured < 0.0 || WhiteMeasured < 0.0)
		{
			return Fail(TEXT("sensing.calibration: a calibration quad is not wholly inside the ")
			            TEXT("calibration frame, so its luminance cannot be measured"));
		}
		EmissiveRecord->SetNumberField(TEXT("nits"), GreyCardNits);
		WhiteRecord->SetNumberField(TEXT("reflectance"), RenderWhiteQuadReflectance);
		WhiteRecord->SetNumberField(TEXT("illuminance_lux"), AppliedSunLux);
		const double GreyMeasured = WhiteMeasured * (RenderGreyCardReflectance / RenderWhiteQuadReflectance);

		// The slanted edge: the centre quad's left edge (local Y = -50),
		// cropped to the middle 60 % of the quad's side about the edge's
		// midpoint, so the crop holds that one edge and nothing else.
		FVector2D EdgeMid, EdgeFar;
		if (!QuadPoint(Quads[1], 0.0, -50.0, EdgeMid) || !QuadPoint(Quads[1], 0.0, 50.0, EdgeFar))
		{
			return Fail(TEXT("sensing.calibration: the slanted-edge quad is behind the calibration camera"));
		}
		const double SidePx = FVector2D::Distance(EdgeMid, EdgeFar);
		const int32 EdgeU0 = FMath::Clamp(FMath::FloorToInt(EdgeMid.X - 0.3 * SidePx), 0, Width);
		const int32 EdgeU1 = FMath::Clamp(FMath::CeilToInt(EdgeMid.X + 0.3 * SidePx), 0, Width);
		const int32 EdgeV0 = FMath::Clamp(FMath::FloorToInt(EdgeMid.Y - 0.3 * SidePx), 0, Height);
		const int32 EdgeV1 = FMath::Clamp(FMath::CeilToInt(EdgeMid.Y + 0.3 * SidePx), 0, Height);
		const double Mtf50 = EsfrMtf50(CalibrationLuminance, Width, Height, EdgeU0, EdgeV0, EdgeU1, EdgeV1);

		// The files: the frame sRGB-encoded for the sensor post-pass, and the
		// linear values themselves.
		const FString CalibrationFrameName = TEXT("calibration_0000.png");
		const FString CalibrationLinearName = TEXT("calibration_0000_linear.f32");
		TArray<FColor> CalibrationPixels;
		CalibrationPixels.SetNumUninitialized(Width * Height);
		TArray<float> CalibrationRgb;
		CalibrationRgb.SetNumUninitialized(Width * Height * RenderLinearChannels);
		for (int32 i = 0; i < CalibrationLinear.Num(); ++i)
		{
			const FLinearColor& C = CalibrationLinear[i];
			CalibrationPixels[i] = FColor(RenderSrgb8(C.R), RenderSrgb8(C.G), RenderSrgb8(C.B), 255);
			CalibrationRgb[RenderLinearChannels * i + 0] = C.R;
			CalibrationRgb[RenderLinearChannels * i + 1] = C.G;
			CalibrationRgb[RenderLinearChannels * i + 2] = C.B;
		}
		TArray64<uint8> CalibrationPng;
		FImageUtils::PNGCompressImageArray(Width, Height, CalibrationPixels, CalibrationPng);
		if (!FFileHelper::SaveArrayToFile(CalibrationPng, *FPaths::Combine(OutputDirectory, CalibrationFrameName))
		    || !WriteLinearF32(FPaths::Combine(OutputDirectory, CalibrationLinearName), CalibrationRgb,
		                       Width, Height, RenderLinearChannels))
		{
			return Fail(TEXT("calibration: could not write the calibration frame"));
		}

		Calibration = MakeShared<FJsonObject>();
		Calibration->SetStringField(TEXT("frame"), CalibrationFrameName);
		Calibration->SetStringField(TEXT("sha256"), RenderSha256Hex(CalibrationPng.GetData(), CalibrationPng.Num()));
		Calibration->SetStringField(TEXT("frame_encoding"),
			TEXT("8-bit PNG: the linear frame sRGB-encoded (IEC 61966-2-1), clamped to [0, 1]; no tonemapper"));
		Calibration->SetStringField(TEXT("linear_f32"), CalibrationLinearName);
		Calibration->SetStringField(TEXT("linear_f32_layout"),
			TEXT("little-endian float32, no header, row-major from the top-left pixel, R G B per pixel ")
			TEXT("(width * height * 3 values)"));
		Calibration->SetNumberField(TEXT("ev100"), AppliedEv100);
		Calibration->SetNumberField(TEXT("exposure_compensation_ev"), ExposureCompensation);
		Calibration->SetNumberField(TEXT("lens_attenuation"), LensAttenuation);
		Calibration->SetStringField(TEXT("lens_attenuation_basis"), LensAttenuationBasis);
		Calibration->SetNumberField(TEXT("calibration_constant"), RenderCalibrationConstant);
		Calibration->SetNumberField(TEXT("luminance_cd_m2_per_unit"), PerUnit);
		Calibration->SetNumberField(TEXT("sun_lux"), AppliedSunLux);
		Calibration->SetStringField(TEXT("sun_lux_source"), SunLuxSource);
		Calibration->SetNumberField(TEXT("grey_card_nits"), GreyCardNits);
		Calibration->SetStringField(TEXT("grey_card_nits_basis"),
			TEXT("stated: the 18 % grey card's rho E / pi under the sun, so the emissive quad and the ")
			TEXT("lit card are predicted to read alike"));
		Calibration->SetNumberField(TEXT("grey_card_reflectance"), RenderGreyCardReflectance);
		Calibration->SetNumberField(TEXT("predicted"), GreyPredicted);
		Calibration->SetNumberField(TEXT("measured"), GreyMeasured);
		Calibration->SetNumberField(TEXT("ratio"), GreyMeasured / GreyPredicted);
		Calibration->SetNumberField(TEXT("tolerance"), RenderCalibrationTolerance);
		Calibration->SetStringField(TEXT("basis"),
			TEXT("predicted, measured and ratio are the 18 % grey card's: the white Lambertian quad's ")
			TEXT("measurement scaled by 0.18 / 0.9 (the ratio is the white quad's own)"));
		Calibration->SetObjectField(TEXT("emissive"), EmissiveRecord);
		Calibration->SetObjectField(TEXT("lambertian"), WhiteRecord);
		TSharedPtr<FJsonObject> Edge = MakeShared<FJsonObject>();
		Edge->SetStringField(TEXT("frame"), CalibrationFrameName);
		Edge->SetArrayField(TEXT("quad_px"), QuadArray(EdgeU0, EdgeV0, EdgeU1, EdgeV1));
		Edge->SetNumberField(TEXT("angle_deg"), RenderSlantedEdgeAngleDeg);
		Edge->SetNumberField(TEXT("nits"), GreyCardNits);
		Calibration->SetObjectField(TEXT("slanted_edge"), Edge);
		if (Mtf50 > 0.0)
		{
			Calibration->SetNumberField(TEXT("mtf50_measured"), Mtf50);
		}
		else
		{
			Calibration->SetField(TEXT("mtf50_measured"), MakeShared<FJsonValueNull>());
		}
		Calibration->SetStringField(TEXT("mtf50_basis"),
			TEXT("the engine's own frame before any sensor stage: this commandlet's e-SFR (EsfrMtf50) ")
			TEXT("on the slanted-edge crop of the linear calibration frame, cycles per pixel, no ")
			TEXT("finite-difference correction; the verifier measures the sensor frame itself"));
		TSharedPtr<FJsonObject> CaptureRecord = MakeShared<FJsonObject>();
		CaptureRecord->SetStringField(TEXT("source"), TEXT("SCS_FinalColorHDR into RTF_RGBA32f, the beauty's exposure"));
		CaptureRecord->SetStringField(TEXT("show_only"), TEXT("the three quads (PRM_UseShowOnlyList)"));
		CaptureRecord->SetStringField(TEXT("off"),
			TEXT("anti-aliasing, temporal AA, fog, volumetric fog, atmosphere, cloud, bloom, motion blur, ")
			TEXT("depth of field, lens flares, translucency, vignette, sky lighting, global illumination, ")
			TEXT("Lumen GI and reflections, ambient occlusion, reflection environment, screen-space ")
			TEXT("reflections, dynamic shadows"));
		CaptureRecord->SetStringField(TEXT("sun"),
			TEXT("atmosphere sun light off (no transmittance on the stated lux), cast shadows off, ")
			TEXT("cloud shadows off, for this frame only (the last render)"));
		CaptureRecord->SetNumberField(TEXT("distance_m"), RenderCalibrationDistanceM);
		Calibration->SetObjectField(TEXT("capture"), CaptureRecord);
		TArray<TSharedPtr<FJsonValue>> CalibrationNotClaimed;
		for (const TCHAR* Line : {
			     TEXT("that one emissive unit is 1 cd/m^2: the emissive quad measures it"),
			     TEXT("the beauty frames' sun after the atmosphere's transmittance: this frame turns it off"),
			     TEXT("a traceable reference luminance: the chain is ISO 2720 / ISO 12232 arithmetic")})
		{
			CalibrationNotClaimed.Add(MakeShared<FJsonValueString>(Line));
		}
		Calibration->SetArrayField(TEXT("not_claimed"), CalibrationNotClaimed);
		FString CalibrationText;
		const TSharedRef<TJsonWriter<>> CalibrationWriter = TJsonWriterFactory<>::Create(&CalibrationText);
		FJsonSerializer::Serialize(Calibration.ToSharedRef(), CalibrationWriter);
		if (!FFileHelper::SaveStringToFile(CalibrationText, *FPaths::Combine(OutputDirectory, TEXT("calibration.json"))))
		{
			return Fail(TEXT("calibration: could not write calibration.json"));
		}
		UE_LOG(LogFlightSimRender, Display,
		       TEXT("calibration: grey card measured / predicted %.4f (white quad), emissive %.4f, ")
		       TEXT("MTF50 %.4f cycles/px on the slanted edge"),
		       GreyMeasured / GreyPredicted, EmissiveMeasured / EmissivePredicted, Mtf50);
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
	// I6 (gap S3): what the ground-truth passes wrote and how each file
	// is encoded, so a reader of render.json alone can decode them
	// (ASCII only -- gotcha 13). Absent when no pass ran.
	if (bPasses)
	{
		TSharedPtr<FJsonObject> Passes = MakeShared<FJsonObject>();
		if (bPassNormal)
		{
			TSharedPtr<FJsonObject> Normal = MakeShared<FJsonObject>();
			Normal->SetStringField(TEXT("file"), TEXT("frame_NNNN_normal.png"));
			Normal->SetStringField(TEXT("encoding"),
				TEXT("16-bit RGBA PNG; R,G,B = (n * 0.5 + 0.5) * 65535 for the unit normal n; A = 65535"));
			Normal->SetStringField(TEXT("frame"),
				TEXT("scene (north, east, up), +up is the third channel; camera-space is R * n with R "
				     "the camera's (right, -up, forward) rows from the manifest quaternion"));
			Normal->SetStringField(TEXT("material"), RenderPassNormalMaterialPath);
			Normal->SetStringField(TEXT("scene_texture"), TEXT("PPI_WorldNormal"));
			Normal->SetStringField(TEXT("anti_aliasing"), TEXT("none"));
			Normal->SetStringField(TEXT("not_claimed"),
				TEXT("sky pixels (the depth file says where): the cleared GBuffer normal"));
			Passes->SetObjectField(TEXT("normal"), Normal);
		}
		if (bPassVelocity)
		{
			TSharedPtr<FJsonObject> Velocity = MakeShared<FJsonObject>();
			Velocity->SetStringField(TEXT("file"), TEXT("frame_NNNN_flow.f32"));
			Velocity->SetStringField(TEXT("encoding"),
				TEXT("little-endian float32 pairs (dx, dy), row-major, width*height pairs, pixels; "
				     "screen +x right, +y down; the displacement of the surface at this pixel from "
				     "the previous captured frame of this pass to this one"));
			Velocity->SetStringField(TEXT("first_frame"),
				TEXT("all zeros, flagged flow_first_frame: true on its record"));
			Velocity->SetStringField(TEXT("material"), RenderPassVelocityMaterialPath);
			Velocity->SetStringField(TEXT("scene_texture"), TEXT("PPI_Velocity"));
			Velocity->SetStringField(TEXT("anti_aliasing"), TEXT("none"));
			Velocity->SetStringField(TEXT("not_claimed"),
				TEXT("the time base equals the capture interval (engine source reading; graded by "
				     "the verifier's flow_vs_motion on a rendered bundle); the beauty frame's "
				     "digest with this pass on equals the digest without it"));
			Passes->SetObjectField(TEXT("velocity"), Velocity);
		}
		if (bPassAlbedo)
		{
			TSharedPtr<FJsonObject> Albedo = MakeShared<FJsonObject>();
			Albedo->SetStringField(TEXT("file"), TEXT("frame_NNNN_albedo.png"));
			Albedo->SetStringField(TEXT("encoding"),
				TEXT("16-bit RGBA PNG; R,G,B = linear base colour in [0, 1] * 65535; A = 65535"));
			Albedo->SetStringField(TEXT("material"), RenderPassBaseColorMaterialPath);
			Albedo->SetStringField(TEXT("scene_texture"), TEXT("PPI_BaseColor"));
			Albedo->SetStringField(TEXT("anti_aliasing"), TEXT("none"));
			Albedo->SetStringField(TEXT("not_claimed"),
				TEXT("sun invariance is measured by Gate 6's albedo clause on Windows, not here"));
			Passes->SetObjectField(TEXT("albedo"), Albedo);
		}
		Root->SetObjectField(TEXT("passes"), Passes);
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
			// I6: set to 1 by -passes=velocity so static geometry writes a
			// motion vector; read back like the rest.
			TEXT("r.Velocity.ForceOutput"),
			// S4: the calibration chain's lens attenuation A (core/capture/
			// radiometry.py reads it back from here), pre-exposure (the
			// scene colour's storage scale), and where the velocity is
			// written (the velocity passes read that buffer). r.Substrate is
			// above: the SCS_BaseColor capture reads the legacy GBuffer.
			TEXT("r.EyeAdaptation.LensAttenuation"),
			TEXT("r.UsePreExposure"),
			TEXT("r.VelocityOutputPass"),
			// W5: the world's measured toggles, read back (each a Windows
			// on/off clause, no benefit claimed): Nanite on the Landscape,
			// streaming virtual textures, MegaLights (the runway lights'
			// probe) -- r.Substrate is above.
			TEXT("landscape.RenderNanite"),
			TEXT("r.VirtualTextures"),
			TEXT("r.MegaLights"),
			TEXT("r.MegaLights.EnableForProject"),
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
		if (AccumulateCapture != nullptr)
		{
			// S4: the accumulation capture's own flag, measured like the rest.
			AntiAliasing->SetStringField(TEXT("accumulate"),
				AntiAliasingName(AccumulateCapture->ShowFlags.AntiAliasing != 0));
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
		// S4: the working colour space the linear frames are in, READ BACK
		// from the engine (core/capture/radiometry.py reads this key; its
		// WORKING_COLOUR_SPACE_DEFAULT is this exact sentence for sRGB).
		{
			const UE::Color::FColorSpace& Working = UE::Color::FColorSpace::GetWorking();
			if (Working.IsSRGB())
			{
				RenderSettings->SetStringField(TEXT("working_colour_space"),
				                               TEXT("sRGB / Rec.709 primaries, linear"));
			}
			else
			{
				RenderSettings->SetStringField(TEXT("working_colour_space"), FString::Printf(
					TEXT("non-sRGB primaries, linear: red (%.4f, %.4f), green (%.4f, %.4f), ")
					TEXT("blue (%.4f, %.4f), white (%.4f, %.4f)"),
					Working.GetRedChromaticity().X, Working.GetRedChromaticity().Y,
					Working.GetGreenChromaticity().X, Working.GetGreenChromaticity().Y,
					Working.GetBlueChromaticity().X, Working.GetBlueChromaticity().Y,
					Working.GetWhiteChromaticity().X, Working.GetWhiteChromaticity().Y));
			}
		}
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
		if (bLookRainRate)
		{
			Look->SetNumberField(TEXT("card_precipitation_rate_mmh"), LookRainRateMmh);
		}
		if (bLookRainExtinction)
		{
			Look->SetNumberField(TEXT("card_rain_extinction_per_m"), LookRainExtinction);
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
		// S4: a sun in lux under the Phase 10 bias path. The -exposure-bias
		// values on record (9.5 / 10.5 / 11.0) are the OLD scale, tuned on
		// the unitless 8.0 sun; under a sun in lux they over-expose by
		// log2(lux / 8) stops until Gate 6's four exposure clauses are
		// re-pinned on the box. Recorded with the number, never corrected.
		const TSharedPtr<FJsonObject>* LookSun = nullptr;
		if (AppliedSunLux > 0.0 && Look->TryGetObjectField(TEXT("sun"), LookSun) && LookSun != nullptr
		    && LookSun->IsValid())
		{
			(*LookSun)->SetStringField(TEXT("exposure_mode"), ExposureMode);
			if (ExposureMode == TEXT("manual_bias"))
			{
				(*LookSun)->SetNumberField(TEXT("bias_overexposure_stops"),
				                           FMath::Log2(AppliedSunLux / RenderEngineSunUnitless));
			}
		}
		Root->SetObjectField(TEXT("look_applied"), Look);
	}
	// S4: the calibration frame's record (the same object as calibration.json).
	if (Calibration.IsValid())
	{
		Root->SetObjectField(TEXT("calibration"), Calibration);
	}
	// W5: world_applied -- what the scene level and the world look drew, the
	// ten keys (landscape, imagery, land_cover, vegetation, buildings, runway,
	// night, precipitation, cloud_drift, materials), each row saying whether
	// the card or -scene= asked for it; graded by core/capture/verify.py
	// check.world_record where present. Absent (render.json byte-identical to
	// before) when the card carries no world or look block and no -scene= was
	// given.
	if (bVisual && bWorldAsked && VisualScene.WorldApplied.IsValid())
	{
		TSharedPtr<FJsonObject> WorldRecord = VisualScene.WorldApplied;
		const TSharedPtr<FJsonObject>* Vegetation = nullptr;
		if (WorldRecord->TryGetObjectField(TEXT("vegetation"), Vegetation) && Vegetation != nullptr)
		{
			// The stencil the aggregates carried in this pass (0 without -labels).
			int32 VegetationId = 0, BuildingId = 0;
			for (const FRenderLabelledObject& Entry : Labelled)
			{
				if (Entry.Id == FlightSimWorld::VegetationObjectId) { VegetationId = Entry.IntId; }
				if (Entry.Id == FlightSimWorld::BuildingObjectId) { BuildingId = Entry.IntId; }
			}
			(*Vegetation)->SetNumberField(TEXT("int_id"), VegetationId);
			const TSharedPtr<FJsonObject>* Buildings = nullptr;
			if (WorldRecord->TryGetObjectField(TEXT("buildings"), Buildings) && Buildings != nullptr)
			{
				(*Buildings)->SetNumberField(TEXT("int_id"), BuildingId);
			}
		}
		const TSharedPtr<FJsonObject>* LandCover = nullptr;
		if (WorldRecord->TryGetObjectField(TEXT("land_cover"), LandCover) && LandCover != nullptr)
		{
			(*LandCover)->SetBoolField(TEXT("drawn"), LabelLandcover != nullptr);
			(*LandCover)->SetStringField(TEXT("file"), TEXT("frame_NNNN_landcover_id.png"));
			(*LandCover)->SetStringField(TEXT("encoding"),
				TEXT("8-bit grey PNG: the WorldCover legend code of the terrain under each pixel, ")
				TEXT("0 for sky and every non-terrain id; AA-free; labels.landcover_png per frame"));
			(*LandCover)->SetNumberField(TEXT("terrain_stencil"), LabelTerrainIntId);
		}
		Root->SetObjectField(TEXT("world_applied"), WorldRecord);
	}
	// S4: how every linear file this pass wrote is laid out, so a reader of
	// render.json alone decodes it (ASCII only -- gotcha 13). Absent when
	// none ran.
	if (LinearNormal != nullptr || LinearBaseColor != nullptr || VelocityCheck != nullptr
	    || AccumulateCapture != nullptr)
	{
		TSharedPtr<FJsonObject> LinearPasses = MakeShared<FJsonObject>();
		LinearPasses->SetStringField(TEXT("layout"),
			TEXT("raw little-endian IEEE-754 float32, no header, row-major from the top-left pixel, ")
			TEXT("the channels of a pixel interleaved: width * height * channels values"));
		if (LinearNormal != nullptr)
		{
			TSharedPtr<FJsonObject> Normal = MakeShared<FJsonObject>();
			Normal->SetStringField(TEXT("file"), TEXT("frame_NNNN_normal.f32"));
			Normal->SetNumberField(TEXT("channels"), RenderLinearChannels);
			Normal->SetStringField(TEXT("axes"), RenderNormalAxes);
			Normal->SetStringField(TEXT("values"), TEXT("the unit normal in the scene frame; 0, 0, 0 for sky"));
			Normal->SetStringField(TEXT("source"), LinearNormalSource);
			Normal->SetStringField(TEXT("encoding"),
				TEXT("measured per frame on the geometry pixels (labels.normal_encoding: signed or ")
				TEXT("offset_half) and decoded before writing"));
			Normal->SetStringField(TEXT("target"), TEXT("RTF_RGBA16f"));
			LinearPasses->SetObjectField(TEXT("normal"), Normal);
		}
		if (LinearBaseColor != nullptr)
		{
			TSharedPtr<FJsonObject> BaseColor = MakeShared<FJsonObject>();
			BaseColor->SetStringField(TEXT("file"), TEXT("frame_NNNN_basecolor.f32"));
			BaseColor->SetNumberField(TEXT("channels"), RenderLinearChannels);
			BaseColor->SetStringField(TEXT("values"),
				TEXT("linear R, G, B base colour as the GBuffer holds it, unclamped; 0, 0, 0 for sky"));
			BaseColor->SetStringField(TEXT("source"), TEXT("SCS_BaseColor"));
			BaseColor->SetStringField(TEXT("target"), TEXT("RTF_RGBA16f"));
			BaseColor->SetStringField(TEXT("not_claimed"),
				TEXT("sun invariance: the two-suns albedo clause is measured on Windows"));
			LinearPasses->SetObjectField(TEXT("basecolor"), BaseColor);
		}
		if (VelocityCheck != nullptr)
		{
			TSharedPtr<FJsonObject> Velocity = MakeShared<FJsonObject>();
			Velocity->SetStringField(TEXT("file"), TEXT("frame_NNNN_velocity.f32"));
			Velocity->SetNumberField(TEXT("channels"), 2);
			Velocity->SetStringField(TEXT("values"),
				TEXT("(dx, dy) pixels, screen +x right, +y down, since the previous captured frame; ")
				TEXT("all zeros on the first"));
			Velocity->SetStringField(TEXT("material"), RenderVelocityCheckMaterialPath);
			Velocity->SetStringField(TEXT("role"),
				TEXT("a read-back cross-check beside the Python flow (core/capture/passes.py), never the truth"));
			LinearPasses->SetObjectField(TEXT("velocity"), Velocity);
		}
		if (AccumulateCapture != nullptr)
		{
			TSharedPtr<FJsonObject> Accumulate = MakeShared<FJsonObject>();
			Accumulate->SetStringField(TEXT("file"), TEXT("frame_NNNN_linear.exr"));
			Accumulate->SetNumberField(TEXT("requested_k"), AccumulateRequested);
			Accumulate->SetNumberField(TEXT("exposure_s"), ExposureShutterSeconds);
			Accumulate->SetStringField(TEXT("values"),
				TEXT("the mean of k AA-free linear sub-exposures over [t0_s, t1_s] (frame_records[].accumulation)"));
			LinearPasses->SetObjectField(TEXT("accumulate"), Accumulate);
		}
		Root->SetObjectField(TEXT("linear_passes"), LinearPasses);
	}
	TSharedPtr<FJsonObject> Scene = MakeShared<FJsonObject>();
	Scene->SetBoolField(TEXT("visual"), bVisual);
	Scene->SetStringField(TEXT("shot"), Shot);
	Scene->SetBoolField(TEXT("dynamic_shadows"), !bNoShadows);
	Scene->SetBoolField(TEXT("aircraft_hidden"), bHideAircraft);
	// Visual plan V0: which renderer configuration produced these frames.
	// Numbers and ASCII only (gotcha 13).
	Scene->SetStringField(TEXT("render_quality"), Quality);
	Scene->SetNumberField(TEXT("warmup_captures"), WarmupCaptures);
	Scene->SetNumberField(TEXT("cvar_anti_aliasing_method"), AntiAliasingMethod);
	Scene->SetNumberField(TEXT("cvar_virtual_shadow_maps"), VirtualShadowMaps);
	Scene->SetStringField(TEXT("gi_reflections"), (bVisual && bBeauty)
		? TEXT("Lumen GI + Lumen reflections (capture post-process override)")
		: TEXT("engine default (no override)"));
	Scene->SetStringField(TEXT("exposure"), bPhysicalSky
		? *FString::Printf(TEXT("manual physical camera, EV100 %.2f (f/%.1f, "
		                        "1/%.0f s, ISO %.0f, bias %.2f)"),
		                   SkyPlan.Ev100, SkyPlan.CameraFstop,
		                   SkyPlan.CameraShutterPerSecond, SkyPlan.CameraIso,
		                   SkyPlan.ExposureBias)
		: (bVisual && !bAutoExposure)
		? (bAppliedEv100
			? *FString::Printf(TEXT("manual, EV100 %.2f (physical camera)"), AppliedEv100)
			: *FString::Printf(TEXT("manual, AutoExposureBias %.1f"), ExposureBias))
		: TEXT("auto (default metering)"));
	Scene->SetBoolField(TEXT("physical_sky"), bPhysicalSky);
	if (bPhysicalSky)
	{
		// The plan itself (sky.json) is the full record; these are what the
		// host actually built from it.
		TSharedPtr<FJsonObject> SkyJson = MakeShared<FJsonObject>();
		SkyJson->SetStringField(TEXT("plan"), SkyPlan.SourcePath);
		SkyJson->SetStringField(TEXT("instant_utc"), SkyPlan.InstantUtc);
		SkyJson->SetNumberField(TEXT("sun_azimuth_deg"), SkyPlan.SunAzimuthDeg);
		SkyJson->SetNumberField(TEXT("sun_elevation_deg"), SkyPlan.SunElevationDeg);
		SkyJson->SetNumberField(TEXT("sun_illuminance_lux"), SkyPlan.SunIlluminanceLux);
		SkyJson->SetNumberField(TEXT("moon_azimuth_deg"), SkyPlan.MoonAzimuthDeg);
		SkyJson->SetNumberField(TEXT("moon_elevation_deg"), SkyPlan.MoonElevationDeg);
		SkyJson->SetNumberField(TEXT("moon_illuminated_fraction"),
		                        SkyPlan.MoonIlluminatedFraction);
		SkyJson->SetBoolField(TEXT("moon_above_horizon"), VisualScene.PhysicalSky.bMoonDrawn);
		SkyJson->SetNumberField(TEXT("stars_drawn"), VisualScene.PhysicalSky.StarsDrawn);
		SkyJson->SetBoolField(TEXT("clouds_drawn"), VisualScene.PhysicalSky.bCloudsDrawn);
		SkyJson->SetStringField(TEXT("clouds_note"), VisualScene.PhysicalSky.CloudsNote);
		SkyJson->SetNumberField(TEXT("ev100"), SkyPlan.Ev100);
		SkyJson->SetStringField(TEXT("global_illumination"), TEXT("lumen"));
		SkyJson->SetStringField(TEXT("reflections"), TEXT("lumen"));
		SkyJson->SetStringField(TEXT("shadows"), TEXT("virtual shadow maps"));
		SkyJson->SetStringField(TEXT("post_process"), SkyPlan.PostKind);
		SkyJson->SetNumberField(TEXT("warmup_captures"), WarmupCaptures);
		SkyJson->SetStringField(TEXT("night_lights_sha256"),
		                        VisualScene.NightLightsSha256);
		SkyJson->SetStringField(TEXT("night_lights_attribution"),
		                        VisualScene.NightLightsAttribution);
		SkyJson->SetStringField(TEXT("night_lights_note"),
		                        VisualScene.NightLightsNote);
		Scene->SetObjectField(TEXT("sky"), SkyJson);
	}
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
	if (bSunLuxFlag || AppliedSunLux > 0.0)
	{
		// S4: whether a sun in lux reached a light (the void tier has none;
		// look_applied.sun carries the lux when it did).
		Scene->SetBoolField(TEXT("sun_lux_applied"), bVisual && AppliedSunLux > 0.0);
	}
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
	// P9: what the physics blocks did (core/capture/verify.py check.host_physics
	// grades each key where present), beside this commandlet's own keys.
	Scenario.AppendEnvironmentReport(Card, Environment);
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
