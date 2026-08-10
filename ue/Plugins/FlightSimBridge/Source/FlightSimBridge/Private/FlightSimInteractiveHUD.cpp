#include "FlightSimInteractiveHUD.h"

#include "FlightSimInteractiveMode.h"

#include "Engine/Canvas.h"
#include "Engine/Font.h"
#include "Engine/World.h"

void AFlightSimInteractiveHUD::DrawHUD()
{
	Super::DrawHUD();

	AFlightSimInteractiveMode* Mode =
		GetWorld() ? GetWorld()->GetAuthGameMode<AFlightSimInteractiveMode>()
		           : nullptr;
	if (Mode == nullptr || Canvas == nullptr)
	{
		return;
	}

	const TArray<FFlightSimHudLine> Lines = Mode->HudLines();
	if (Lines.Num() == 0)
	{
		return;
	}

	UFont* Font = GEngine->GetMediumFont();
	const float Margin = 12.0f;
	const float LineHeight = 16.0f;

	// A backing strip so the text stays legible over snow and sky alike --
	// the same reason the clip panel is a solid strip below the frame.
	float MaxWidth = 0.0f;
	for (const FFlightSimHudLine& Line : Lines)
	{
		float Width = 0.0f, Height = 0.0f;
		Canvas->TextSize(Font, Line.Text, Width, Height);
		MaxWidth = FMath::Max(MaxWidth, Width);
	}
	FCanvasTileItem Backing(
		FVector2D(Margin - 6.0f, Margin - 6.0f),
		FVector2D(MaxWidth + 12.0f, Lines.Num() * LineHeight + 12.0f),
		FLinearColor(0.0f, 0.0f, 0.0f, 0.55f));
	Backing.BlendMode = SE_BLEND_Translucent;
	Canvas->DrawItem(Backing);

	float Y = Margin;
	for (const FFlightSimHudLine& Line : Lines)
	{
		FCanvasTextItem Item(FVector2D(Margin, Y), FText::FromString(Line.Text),
		                     Font, Line.Colour);
		Canvas->DrawItem(Item);
		Y += LineHeight;
	}
}
