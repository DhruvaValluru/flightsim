# Hardware probe: writes docs/hardware/hardware_profile.json from THIS Windows machine.
# The hyper-realism swarm (swarm/README.md) sizes every work item from that file.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\hw_probe.ps1
#
# Read-only: it queries CIM, nvidia-smi and the registry and writes one JSON file.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))

function Try-Cim($cls) { try { Get-CimInstance $cls -ErrorAction Stop } catch { $null } }

$cpu = Try-Cim Win32_Processor | Select-Object -First 1
$ram = Try-Cim Win32_PhysicalMemory
$os  = Try-Cim Win32_OperatingSystem
$gpus = @()

# NVIDIA: nvidia-smi is the only reliable VRAM source (Win32_VideoController caps at 4 GB).
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) {
  $q = "name,memory.total,driver_version,clocks.max.graphics,clocks.max.memory,power.limit,pcie.link.gen.max,pcie.link.width.max"
  & nvidia-smi --query-gpu=$q --format=csv,noheader,nounits 2>$null | ForEach-Object {
    $f = $_ -split ",\s*"
    if ($f.Count -ge 8) {
      $gpus += [ordered]@{
        vendor = "nvidia"; name = $f[0]; vram_mb = [int]$f[1]; driver = $f[2]
        max_gfx_mhz = [int]$f[3]; max_mem_mhz = [int]$f[4]; power_limit_w = $f[5]
        pcie_gen = $f[6]; pcie_width = $f[7]
      }
    }
  }
}
if ($gpus.Count -eq 0) {
  # AMD / Intel: registry qwMemorySize is 64-bit, AdapterRAM is not.
  $reg = "HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
  Get-ChildItem $reg -ErrorAction SilentlyContinue | ForEach-Object {
    $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
    if ($p.DriverDesc -and $p."HardwareInformation.qwMemorySize") {
      $vendor = if ($p.DriverDesc -match "AMD|Radeon") { "amd" } elseif ($p.DriverDesc -match "Intel") { "intel" } else { "other" }
      $gpus += [ordered]@{ vendor = $vendor; name = $p.DriverDesc
        vram_mb = [int]([uint64]$p."HardwareInformation.qwMemorySize" / 1MB); driver = $p.DriverVersion }
    }
  }
}

$disks = @()
Try-Cim MSFT_PhysicalDisk | Out-Null
try { Get-PhysicalDisk | ForEach-Object { $disks += [ordered]@{ name = $_.FriendlyName; media = "$($_.MediaType)"; bus = "$($_.BusType)"; size_gb = [math]::Round($_.Size / 1GB) } } } catch {}
$cacheDrive = if ($env:FLIGHTSIM_CACHE) { (Split-Path -Qualifier $env:FLIGHTSIM_CACHE) } else { "C:" }
$free = try { [math]::Round((Get-PSDrive ($cacheDrive.TrimEnd(":"))).Free / 1GB) } catch { $null }

$disp = Try-Cim Win32_VideoController | Select-Object -First 1
$profile = [ordered]@{
  schema = 1
  cpu = [ordered]@{ name = $cpu.Name.Trim(); physical_cores = $cpu.NumberOfCores; logical_cores = $cpu.NumberOfLogicalProcessors; max_mhz = $cpu.MaxClockSpeed }
  ram = [ordered]@{ total_gb = [math]::Round((($ram | Measure-Object Capacity -Sum).Sum) / 1GB); speed_mhz = ($ram | Select-Object -First 1).Speed; modules = @($ram).Count }
  gpus = $gpus
  display = [ordered]@{ width = $disp.CurrentHorizontalResolution; height = $disp.CurrentVerticalResolution; refresh_hz = $disp.CurrentRefreshRate }
  disks = $disks
  cache_free_gb = $free
  os = [ordered]@{ caption = $os.Caption; build = $os.BuildNumber }
  ue_root = $env:UE_ROOT
}
New-Item -ItemType Directory -Force -Path docs\hardware | Out-Null
$profile | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 docs\hardware\hardware_profile.json
Write-Host "wrote docs\hardware\hardware_profile.json"
$profile | ConvertTo-Json -Depth 6
