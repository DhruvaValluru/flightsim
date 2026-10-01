#include "FlightSimLandscapeImporter.h"

#include "FlightSimVisualScene.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "Dom/JsonObject.h"
#include "Engine/World.h"
#include "Landscape.h"
#include "LandscapeInfo.h"
#include "LandscapeLayerInfoObject.h"
#include "LandscapeProxy.h"
#include "LandscapeSubsystem.h"
#include "Materials/MaterialInterface.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/Package.h"
#include "UObject/UnrealType.h"

DEFINE_LOG_CATEGORY(LogFlightSimWorld);

namespace
{
	// FIPS 180-4 SHA-256 as hex; this module's own copy (unity builds merge
	// anonymous namespaces, so the name is unique to the file). The layer
	// files' digests are the ones core/terrain/weightmaps.py recorded.
	FString EditorSha256Hex(const uint8* Data, int64 Length)
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
		const uint64 Bits = static_cast<uint64>(Length) * 8u;
		const int64 Padded = ((Length + 8) / 64 + 1) * 64;
		TArray<uint8> Buffer;
		Buffer.SetNumZeroed(Padded);
		FMemory::Memcpy(Buffer.GetData(), Data, Length);
		Buffer[Length] = 0x80;
		for (int32 i = 0; i < 8; ++i)
		{
			Buffer[Padded - 1 - i] = static_cast<uint8>(Bits >> (8 * i));
		}
		auto Rotr = [](uint32 X, uint32 N) { return (X >> N) | (X << (32 - N)); };
		for (int64 Chunk = 0; Chunk < Padded; Chunk += 64)
		{
			uint32 W[64];
			for (int32 i = 0; i < 16; ++i)
			{
				const uint8* P = Buffer.GetData() + Chunk + i * 4;
				W[i] = (uint32(P[0]) << 24) | (uint32(P[1]) << 16) | (uint32(P[2]) << 8) | uint32(P[3]);
			}
			for (int32 i = 16; i < 64; ++i)
			{
				const uint32 S0 = Rotr(W[i-15], 7) ^ Rotr(W[i-15], 18) ^ (W[i-15] >> 3);
				const uint32 S1 = Rotr(W[i-2], 17) ^ Rotr(W[i-2], 19) ^ (W[i-2] >> 10);
				W[i] = W[i-16] + S0 + W[i-7] + S1;
			}
			uint32 A=H[0],B=H[1],C=H[2],D=H[3],E=H[4],F=H[5],G=H[6],Hh=H[7];
			for (int32 i = 0; i < 64; ++i)
			{
				const uint32 S1 = Rotr(E,6) ^ Rotr(E,11) ^ Rotr(E,25);
				const uint32 Ch = (E & F) ^ (~E & G);
				const uint32 T1 = Hh + S1 + Ch + K[i] + W[i];
				const uint32 S0 = Rotr(A,2) ^ Rotr(A,13) ^ Rotr(A,22);
				const uint32 Maj = (A & B) ^ (A & C) ^ (B & C);
				Hh=G; G=F; F=E; E=D+T1; D=C; C=B; B=A; A=T1+S0+Maj;
			}
			H[0]+=A; H[1]+=B; H[2]+=C; H[3]+=D; H[4]+=E; H[5]+=F; H[6]+=G; H[7]+=Hh;
		}
		FString Hex;
		for (int32 i = 0; i < 8; ++i)
		{
			Hex += FString::Printf(TEXT("%08x"), H[i]);
		}
		return Hex;
	}

	// The valid Landscape layouts (core/terrain/landscape.py
	// VALID_QUADS_PER_SECTION, VALID_SECTIONS_PER_COMPONENT).
	bool EditorValidLayout(int32 Quads, int32 Sections, int32 Components, int32 Resolution)
	{
		const bool bQuads = Quads == 7 || Quads == 15 || Quads == 31 || Quads == 63 ||
		                    Quads == 127 || Quads == 255;
		const bool bSections = Sections == 1 || Sections == 2;
		return bQuads && bSections && Components > 0 &&
		       Resolution == Components * Sections * Quads + 1;
	}

	// Row r of a row-0-north raster goes to Landscape row DestinationRow(r).
	int32 EditorDestinationRow(int32 Row, int32 Resolution, bool bNorthPlusY)
	{
		return bNorthPlusY ? Resolution - 1 - Row : Row;
	}
}

FString UFlightSimLandscapeImporter::TerrainSha256Tag(const FString& Sha256)
{
	return FString(FlightSimWorld::TerrainSha256TagPrefix) + Sha256.ToLower();
}

ALandscape* UFlightSimLandscapeImporter::ImportLandscape(UWorld* World, const FString& ManifestPath,
                                                         const FString& ExpectedBakeSha256,
                                                         const FString& AssetFolder,
                                                         UMaterialInterface* Material,
                                                         const FString& NorthAxis, FString& Report)
{
	auto Refuse = [&Report](const FString& Line) -> ALandscape*
	{
		Report = Line;
		UE_LOG(LogFlightSimWorld, Error, TEXT("%s"), *Line);
		return nullptr;
	};
	if (World == nullptr)
	{
		return Refuse(TEXT("terrain.landscape_missing: no editor world to import the landscape into"));
	}

	// -- the manifest ---------------------------------------------------------
	FString Text;
	TSharedPtr<FJsonObject> Manifest;
	if (!FFileHelper::LoadFileToString(Text, *ManifestPath))
	{
		return Refuse(FString::Printf(
			TEXT("terrain.landscape_missing: the import manifest %s is absent; export the ")
			TEXT("landscape with scripts/bake_landcover.py"), *ManifestPath));
	}
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	if (!FJsonSerializer::Deserialize(Reader, Manifest) || !Manifest.IsValid())
	{
		return Refuse(FString::Printf(
			TEXT("terrain.landscape_missing: the import manifest %s does not parse"), *ManifestPath));
	}
	// The datum block (W1 copies the bake's provenance.datum verbatim): a
	// Landscape whose heights state no vertical datum is the P10 error again.
	const TSharedPtr<FJsonObject>* Datum = nullptr;
	if (!Manifest->TryGetObjectField(TEXT("datum"), Datum) || Datum == nullptr ||
	    !(*Datum)->HasField(TEXT("undulation_m")) ||
	    !(*Datum)->HasField(TEXT("vertical_datum_of_heights")))
	{
		return Refuse(FString::Printf(
			TEXT("terrain.landscape_missing: the import manifest %s carries no datum block ")
			TEXT("(undulation_m, vertical_datum_of_heights); re-bake and export it again"),
			*ManifestPath));
	}
	const TSharedPtr<FJsonObject>* Bake = nullptr;
	FString BakeSha, BakeName;
	if (!Manifest->TryGetObjectField(TEXT("bake"), Bake) || Bake == nullptr ||
	    !(*Bake)->TryGetStringField(TEXT("sha256"), BakeSha))
	{
		return Refuse(FString::Printf(
			TEXT("terrain.landscape_missing: the import manifest %s names no bake (bake.sha256)"),
			*ManifestPath));
	}
	(*Bake)->TryGetStringField(TEXT("name"), BakeName);
	if (!BakeSha.Equals(ExpectedBakeSha256, ESearchCase::IgnoreCase))
	{
		return Refuse(FString::Printf(
			TEXT("terrain.landscape_stale: the manifest was exported from a bake with sha256 %s..., ")
			TEXT("the scene is built for %s...; export the landscape again from the current bake"),
			*BakeSha.Left(12), *ExpectedBakeSha256.Left(12)));
	}

	// -- the layout and the heightmap ------------------------------------------
	double ResolutionValue = 0.0, MinElevation = 0.0, MaxElevation = 0.0;
	const TSharedPtr<FJsonObject>* Layout = nullptr;
	const TSharedPtr<FJsonObject>* Scale = nullptr;
	double Quads = 0.0, Sections = 0.0, Components = 0.0, ScaleX = 0.0, ScaleY = 0.0, ScaleZ = 0.0;
	if (!Manifest->TryGetNumberField(TEXT("resolution"), ResolutionValue) ||
	    !Manifest->TryGetObjectField(TEXT("layout"), Layout) || Layout == nullptr ||
	    !(*Layout)->TryGetNumberField(TEXT("quads_per_section"), Quads) ||
	    !(*Layout)->TryGetNumberField(TEXT("sections_per_component"), Sections) ||
	    !(*Layout)->TryGetNumberField(TEXT("components"), Components) ||
	    !Manifest->TryGetObjectField(TEXT("scale"), Scale) || Scale == nullptr ||
	    !(*Scale)->TryGetNumberField(TEXT("x"), ScaleX) ||
	    !(*Scale)->TryGetNumberField(TEXT("y"), ScaleY) ||
	    !(*Scale)->TryGetNumberField(TEXT("z"), ScaleZ) ||
	    !Manifest->TryGetNumberField(TEXT("min_elevation_m"), MinElevation) ||
	    !Manifest->TryGetNumberField(TEXT("max_elevation_m"), MaxElevation))
	{
		return Refuse(FString::Printf(
			TEXT("terrain.landscape_layout: the import manifest %s lacks the Gate 4 keys (resolution, ")
			TEXT("layout, scale, min/max elevation)"), *ManifestPath));
	}
	const int32 Resolution = static_cast<int32>(ResolutionValue);
	if (!EditorValidLayout(static_cast<int32>(Quads), static_cast<int32>(Sections),
	                       static_cast<int32>(Components), Resolution))
	{
		return Refuse(FString::Printf(
			TEXT("terrain.landscape_layout: %d quads x %d sections x %d components does not make a ")
			TEXT("%d-sample Landscape"), static_cast<int32>(Quads), static_cast<int32>(Sections),
			static_cast<int32>(Components), Resolution));
	}
	const int64 Texels = static_cast<int64>(Resolution) * Resolution;
	// The manifest records the heightmap's file NAME beside itself.
	const FString RawPath = FPaths::ChangeExtension(ManifestPath, TEXT("r16"));
	TArray<uint8> Raw;
	if (!FFileHelper::LoadFileToArray(Raw, *RawPath) || Raw.Num() != Texels * 2)
	{
		return Refuse(FString::Printf(
			TEXT("terrain.landscape_layout: the heightmap %s holds %d bytes, not %lld (%d^2 samples ")
			TEXT("of 16 bits)"), *RawPath, Raw.Num(), Texels * 2, Resolution));
	}
	const bool bNorthPlusY = NorthAxis != TEXT("-Y");
	TArray<uint16> Heights;
	Heights.SetNumUninitialized(Texels);
	for (int32 Row = 0; Row < Resolution; ++Row)
	{
		const int32 Destination = EditorDestinationRow(Row, Resolution, bNorthPlusY);
		for (int32 Column = 0; Column < Resolution; ++Column)
		{
			const int64 Source = static_cast<int64>(Row) * Resolution + Column;
			// Little-endian uint16 (core/terrain/landscape.py writes '<u2').
			Heights[static_cast<int64>(Destination) * Resolution + Column] =
				static_cast<uint16>(Raw[2 * Source]) | (static_cast<uint16>(Raw[2 * Source + 1]) << 8);
		}
	}

	// -- the weight layers: digest, layout, size, then one paint layer each ----
	const FString ManifestDir = FPaths::GetPath(ManifestPath);
	const TArray<TSharedPtr<FJsonValue>>* LayersJson = nullptr;
	TArray<FLandscapeImportLayerInfo> ImportLayers;
	TArray<FString> LayerKeys;
	if (Manifest->TryGetArrayField(TEXT("weight_layers"), LayersJson) && LayersJson != nullptr)
	{
		for (const TSharedPtr<FJsonValue>& Value : *LayersJson)
		{
			const TSharedPtr<FJsonObject> Layer = Value.IsValid() ? Value->AsObject() : nullptr;
			FString Key, File, Digest;
			double LayerResolution = 0.0;
			const TSharedPtr<FJsonObject>* LayerLayout = nullptr;
			double LayerQuads = 0.0, LayerSections = 0.0, LayerComponents = 0.0;
			if (!Layer.IsValid() || !Layer->TryGetStringField(TEXT("key"), Key) ||
			    !Layer->TryGetStringField(TEXT("file"), File) ||
			    !Layer->TryGetStringField(TEXT("sha256"), Digest) ||
			    !Layer->TryGetNumberField(TEXT("resolution"), LayerResolution) ||
			    !Layer->TryGetObjectField(TEXT("layout"), LayerLayout) || LayerLayout == nullptr ||
			    !(*LayerLayout)->TryGetNumberField(TEXT("quads_per_section"), LayerQuads) ||
			    !(*LayerLayout)->TryGetNumberField(TEXT("sections_per_component"), LayerSections) ||
			    !(*LayerLayout)->TryGetNumberField(TEXT("components"), LayerComponents))
			{
				return Refuse(TEXT("terrain.landscape_layout: a weight layer of the manifest lacks its ")
				              TEXT("key, file, sha256, resolution or layout"));
			}
			if (static_cast<int32>(LayerResolution) != Resolution || LayerQuads != Quads ||
			    LayerSections != Sections || LayerComponents != Components)
			{
				return Refuse(FString::Printf(
					TEXT("terrain.landscape_layout: layer %s is laid out for another Landscape than ")
					TEXT("the heightmap; the editor would resample it silently against the geometry"),
					*File));
			}
			TArray<uint8> Bytes;
			const FString LayerPath = FPaths::Combine(ManifestDir, File);
			if (!FFileHelper::LoadFileToArray(Bytes, *LayerPath))
			{
				return Refuse(FString::Printf(
					TEXT("terrain.landscape_stale: the layer file %s is absent"), *LayerPath));
			}
			const FString Measured = EditorSha256Hex(Bytes.GetData(), Bytes.Num());
			if (!Measured.Equals(Digest, ESearchCase::IgnoreCase))
			{
				return Refuse(FString::Printf(
					TEXT("terrain.landscape_stale: the layer file %s hashes to %s..., the manifest ")
					TEXT("recorded %s..."), *LayerPath, *Measured.Left(12), *Digest.Left(12)));
			}
			if (Bytes.Num() != Texels)
			{
				return Refuse(FString::Printf(
					TEXT("terrain.landscape_layout: the layer file %s holds %d bytes, not %d^2"),
					*LayerPath, Bytes.Num(), Resolution));
			}
			// The layer-info asset under the scene's folder, one per class.
			const FString AssetName = TEXT("LI_") + Key;
			const FString PackageName = AssetFolder / TEXT("LayerInfo") / AssetName;
			UPackage* Package = CreatePackage(*PackageName);
			ULandscapeLayerInfoObject* Info = NewObject<ULandscapeLayerInfoObject>(
				Package, FName(*AssetName), RF_Public | RF_Standalone | RF_Transactional);
#if ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 6)
			Info->SetLayerName(FName(*Key), /*bInModify=*/false);
#else
			Info->LayerName = FName(*Key);
#endif
			FAssetRegistryModule::AssetCreated(Info);
			Package->MarkPackageDirty();

			FLandscapeImportLayerInfo Import;
			Import.LayerName = FName(*Key);
			Import.LayerInfo = Info;
			Import.LayerData.SetNumUninitialized(Texels);
			for (int32 Row = 0; Row < Resolution; ++Row)
			{
				const int32 Destination = EditorDestinationRow(Row, Resolution, bNorthPlusY);
				FMemory::Memcpy(Import.LayerData.GetData() + static_cast<int64>(Destination) * Resolution,
				                Bytes.GetData() + static_cast<int64>(Row) * Resolution, Resolution);
			}
			ImportLayers.Add(MoveTemp(Import));
			LayerKeys.Add(Key);
		}
	}

	// -- the Landscape -----------------------------------------------------------
	// The actor's Z is the height sample 32768 encodes (W1's encoding; a flat
	// bake is encoded over 1 m, as landscape.export does).
	const double Relief = MaxElevation > MinElevation ? MaxElevation - MinElevation : 1.0;
	const double ActorZMetres = MinElevation + Relief * 32768.0 / 65535.0;
	ALandscape* Landscape = World->SpawnActor<ALandscape>(
		FVector(0.0, 0.0, ActorZMetres * 100.0), FRotator::ZeroRotator);
	if (Landscape == nullptr)
	{
		return Refuse(TEXT("terrain.landscape_missing: the editor world did not spawn a Landscape"));
	}
	Landscape->SetActorScale3D(FVector(ScaleX, ScaleY, ScaleZ));
	Landscape->LandscapeMaterial = Material;
	TMap<FGuid, TArray<uint16>> HeightDataPerLayer;
	HeightDataPerLayer.Add(FGuid(), MoveTemp(Heights));
	TMap<FGuid, TArray<FLandscapeImportLayerInfo>> MaterialLayerDataPerLayer;
	MaterialLayerDataPerLayer.Add(FGuid(), MoveTemp(ImportLayers));
	// ALandscape::Import(guid, min x, min y, max x, max y, sections per
	// component, quads per section, heights, heightmap file name, layer
	// weights, alpha-map type): weight-blended (the layers sum to 255).
	// UE 5.7 declares the trailing edit-layer list with no default
	// (LandscapeProxy.h, read on the owner's machine): passed empty, the
	// import writes the base layer as 5.5's defaulted call did.
	Landscape->Import(FGuid::NewGuid(), 0, 0, Resolution - 1, Resolution - 1,
	                  static_cast<int32>(Sections), static_cast<int32>(Quads),
	                  HeightDataPerLayer, nullptr, MaterialLayerDataPerLayer,
	                  ELandscapeImportAlphamapType::Additive,
	                  TArrayView<const FLandscapeLayer>());
	if (ULandscapeInfo* Info = Landscape->GetLandscapeInfo())
	{
		Info->UpdateLayerInfoMap(Landscape);
	}
	// The two tags the render reads (FlightSimVisualScene LoadSceneLevel).
	Landscape->Tags.AddUnique(FName(FlightSimWorld::TerrainTag));
	Landscape->Tags.AddUnique(FName(*TerrainSha256Tag(BakeSha)));
	Landscape->SetActorLabel(FString::Printf(TEXT("Landscape_%s"), *BakeName));
	Report = FString::Printf(
		TEXT("imported %s: %dx%d (%d quads x %d sections x %d components), scale %.4f %.4f %.6f, ")
		TEXT("actor Z %.3f m, %d weight layer(s) [%s], north %s, tag %s"),
		*BakeName, Resolution, Resolution, static_cast<int32>(Quads), static_cast<int32>(Sections),
		static_cast<int32>(Components), ScaleX, ScaleY, ScaleZ, ActorZMetres, LayerKeys.Num(),
		*FString::Join(LayerKeys, TEXT(",")), bNorthPlusY ? TEXT("+Y") : TEXT("-Y"),
		*TerrainSha256Tag(BakeSha));
	UE_LOG(LogFlightSimWorld, Display, TEXT("%s"), *Report);
	return Landscape;
}

bool UFlightSimLandscapeImporter::BuildNanite(ALandscape* Landscape, bool bEnable, FString& Report)
{
	if (Landscape == nullptr)
	{
		Report = TEXT("no Landscape to build Nanite for");
		return false;
	}
	// Through reflection: the property is the proxy's bEnableNanite, whose
	// accessors moved between releases; its name did not.
	FBoolProperty* Property = FindFProperty<FBoolProperty>(ALandscapeProxy::StaticClass(),
	                                                       TEXT("bEnableNanite"));
	if (Property == nullptr)
	{
		Report = TEXT("ALandscapeProxy has no bEnableNanite in this build: the Nanite toggle is absent");
		UE_LOG(LogFlightSimWorld, Warning, TEXT("%s"), *Report);
		return false;
	}
	Landscape->Modify();
	Property->SetPropertyValue_InContainer(Landscape, bEnable);
	FPropertyChangedEvent Changed(Property);
	Landscape->PostEditChangeProperty(Changed);
	if (bEnable)
	{
		if (ULandscapeSubsystem* Subsystem = Landscape->GetWorld()->GetSubsystem<ULandscapeSubsystem>())
		{
			Subsystem->BuildNanite();
		}
	}
	const bool bReadBack = Landscape->IsNaniteEnabled();
	Report = FString::Printf(TEXT("Nanite asked %s, IsNaniteEnabled() reads %s"),
	                         bEnable ? TEXT("on") : TEXT("off"), bReadBack ? TEXT("on") : TEXT("off"));
	UE_LOG(LogFlightSimWorld, Display, TEXT("%s"), *Report);
	return bReadBack == bEnable;
}
