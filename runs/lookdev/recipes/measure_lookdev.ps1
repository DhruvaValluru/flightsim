# Measure look-dev batches 1+2 on the Windows laptop (UNMEASURED until run).
# Run from C:\Users\kanth\flightsim with the web app up, the editor CLOSED and
# no other render running:
#   powershell -ExecutionPolicy Bypass -File runs\lookdev\recipes\measure_lookdev.ps1 -Round r200
# It renders stills of scenes 3 and 13 and builds one side-by-side PNG per
# scene: [reference photo | new render] under runs\lookdev\measured\<Round>\.
param([Parameter(Mandatory = $true)][string]$Round)
$ErrorActionPreference = "Stop"
if (Get-Process UnrealEditor -ErrorAction SilentlyContinue) { throw "close the Unreal editor first" }
if (Get-Process UnrealEditor-Cmd -ErrorAction SilentlyContinue) { throw "a render is already running" }
$repo = "C:\Users\kanth\flightsim"
$py = Join-Path $repo ".venv\Scripts\python.exe"   # has Pillow; the global python does not
$out = Join-Path $repo "runs\lookdev\measured\$Round"
New-Item -ItemType Directory -Force $out | Out-Null
& $py (Join-Path $repo "scripts\run_test_scenarios.py") --only 3 13 --still
if ($LASTEXITCODE -ne 0) { throw "run_test_scenarios failed ($LASTEXITCODE)" }
$pairs = @(
    @{ n = 3;  ref = "s03_manhattan_1500ft.jpg" },
    @{ n = 13; ref = "s13_cumulus_from_10-11km.jpg" }
)
foreach ($p in $pairs) {
    $frame = Get-ChildItem (Join-Path $repo "runs\test_scenarios") -Filter ("{0:D2}_*_frame_beauty_post.png" -f $p.n) |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $frame) { Write-Warning "no frame for scene $($p.n)"; continue }
    $ref = Join-Path $repo ("runs\lookdev\refs\real_photos\" + $p.ref)
    $dst = Join-Path $out ("scene{0:D2}_ref_vs_render.png" -f $p.n)
    & $py -I -c "import sys;from PIL import Image;a=Image.open(sys.argv[1]).convert('RGB');b=Image.open(sys.argv[2]).convert('RGB');h=720;a=a.resize((int(a.width*h/a.height),h));b=b.resize((int(b.width*h/b.height),h));c=Image.new('RGB',(a.width+b.width,h));c.paste(a,(0,0));c.paste(b,(a.width,0));c.save(sys.argv[3])" $ref $frame.FullName $dst
    Copy-Item $frame.FullName (Join-Path $out ("scene{0:D2}_render.png" -f $p.n))
    "scene $($p.n): $dst"
}
"MEASURED $Round -> $out (look at both side-by-sides before claiming anything)"
