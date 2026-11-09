# The visual overhaul's four baseline shots, on the Windows render box.
#
#     .\scripts\render_visual_sheet.ps1 -Step v0                      # beauty a b c d + sheet.png
#     .\scripts\render_visual_sheet.ps1 -Step v0 -StillSamples 16     # beauty stills, 16 captures a pose
#     .\scripts\render_visual_sheet.ps1 -Step v0_pt -PathTrace -Spp 512   # path-traced hero stills
#     .\scripts\render_visual_sheet.ps1 -Step v0 -Clip                # + a 15 s chase-cam clip
#     .\scripts\render_visual_sheet.ps1 -Step v0 -SkipRender          # compose from existing PNGs
#     .\scripts\render_visual_sheet.ps1 -Compare v0_before,v0         # before/after sheet
#
# A thin wrapper over experiments\visual_contact_sheet.py (read its
# docstring): the shots go through the web app's own handlers in-process,
# so Google tiles are the ground and the storm weather is on, as on the
# page. Output: runs\visual\<step>\{a,b,c,d}.png, shots.json, sheet.png.
#
# -PathTrace adds -quality=pathtrace and the one-process ray-tracing
# switch (-ini:Engine:[/Script/Engine.RendererSettings]:r.RayTracing=True)
# to the per-camera render pass only; DefaultEngine.ini never carries
# r.RayTracing (it would change every measure render). The first
# path-traced run compiles the ray-tracing shaders and takes long.

param(
    [string]$Step = "",
    [string]$Quality = "beauty",
    [int]$StillSamples = 0,
    [switch]$PathTrace,
    [int]$Spp = 0,
    [switch]$Clip,
    [switch]$SkipRender,
    [string[]]$Compare = @(),
    [string]$Shots = "a,b,c,d"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "REFUSED python.venv: no $python -- run .\scripts\setup.ps1 first"
    exit 3
}

$arguments = @((Join-Path $repo "experiments\visual_contact_sheet.py"))
if ($Compare.Count -gt 0) {
    if ($Compare.Count -ne 2) {
        Write-Host "usage: -Compare <stepA>,<stepB>"
        exit 2
    }
    $arguments += @("--compare", $Compare[0], $Compare[1])
} else {
    if (-not $Step) {
        Write-Host "usage: .\scripts\render_visual_sheet.ps1 -Step <name> [-PathTrace] [-Clip] [-SkipRender]"
        exit 2
    }
    $arguments += @("--step", $Step, "--quality", $Quality, "--shots", $Shots)
    if ($StillSamples -gt 0) { $arguments += @("--still-samples", "$StillSamples") }
    if ($PathTrace) { $arguments += @("--pathtrace") }
    if ($Spp -gt 0) { $arguments += @("--spp", "$Spp") }
    if ($Clip) { $arguments += @("--clip") }
    if ($SkipRender) { $arguments += @("--skip-render") }
}

Push-Location $repo
try {
    & $python @arguments
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code
