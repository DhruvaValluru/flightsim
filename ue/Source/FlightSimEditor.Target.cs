using UnrealBuildTool;

public class FlightSimEditorTarget : TargetRules
{
	public FlightSimEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.V5;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_5;
		ExtraModuleNames.Add("FlightSim");
	}
}
