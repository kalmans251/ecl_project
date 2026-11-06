<#
Configure the existing analytics-server age pipeline without replacing secrets.
Copy YuNet ONNX to models/face_detection_yunet_2023mar.onnx before running.
Optional: -InstallDependencies installs the v2 Python requirements.
#>
param(
    [switch]$InstallDependencies,
    [switch]$UseCpu
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $root 'config.json'
$modelPath = Join-Path $root 'models\face_detection_yunet_2023mar.onnx'
$python = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $configPath)) {
    throw "config.json not found at $configPath. Existing camera ID and token are required."
}
if (-not (Test-Path -LiteralPath $modelPath)) {
    throw "Place YuNet ONNX at $modelPath before running this script. No configuration was changed."
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Existing Python venv not found at $python. No configuration was changed."
}

if ($InstallDependencies) {
    # The upstream MiVOLO setup.py imports pkg_resources at build time.
    # Modern isolated builds can omit it; use a compatible local setuptools.
    & $python -m pip install 'setuptools>=69,<81' wheel
    if ($LASTEXITCODE -ne 0) { throw 'Build tooling installation failed; configuration was not changed.' }
    & $python -m pip install -r (Join-Path $root 'requirements-age-v2.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; configuration was not changed.' }
    # Do not let MiVOLO's old ultralytics==8.1.0 requirement downgrade the
    # project's existing YOLO11 installation.
    & $python -m pip install --no-build-isolation --no-deps 'git+https://github.com/WildChlamydia/MiVOLO.git'
    if ($LASTEXITCODE -ne 0) { throw 'MiVOLO package installation failed; configuration was not changed.' }
}

# Config is an object on both Windows PowerShell 5.1 and PowerShell 7.
$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $config.camera_id -or -not $config.analysis_token -or -not $config.server_url) {
    throw 'Existing config.json is missing camera_id, analysis_token or server_url.'
}
if (-not $config.age) {
    $config | Add-Member -NotePropertyName age -NotePropertyValue ([pscustomobject]@{})
}
function Set-JsonProperty([object]$target, [string]$name, [object]$value) {
    if ($target.PSObject.Properties[$name]) {
        $target.$name = $value
    } else {
        $target | Add-Member -NotePropertyName $name -NotePropertyValue $value
    }
}

Set-JsonProperty $config.age 'backend' 'v2'
Set-JsonProperty $config.age 'model_id' 'iitolstykh/mivolo_v2'
Set-JsonProperty $config.age 'device' $(if ($UseCpu) { 'cpu' } else { 'cuda:0' })
Set-JsonProperty $config.age 'face_model' $modelPath
Set-JsonProperty $config.age 'face_conf' 0.85
Set-JsonProperty $config.age 'min_face_width' 40
Set-JsonProperty $config.age 'min_face_sharpness' 35
Set-JsonProperty $config.age 'require_face' $true
Set-JsonProperty $config.age 'window_seconds' 4
Set-JsonProperty $config.age 'min_samples' 3
Set-JsonProperty $config.age 'enabled' $true

$backup = "$configPath.backup.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item -LiteralPath $configPath -Destination $backup -ErrorAction Stop
$json = $config | ConvertTo-Json -Depth 30
[System.IO.File]::WriteAllText($configPath, $json + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))
Write-Host 'Age analysis settings updated. Existing server URL, camera ID, token and other config fields preserved.'
Write-Host "Backup: $backup"
Write-Warning 'MiVOLO v2 model is licensed CC-BY-NC-4.0. Verify commercial-use permission before production deployment.'
Write-Warning 'First start downloads Hugging Face model weights. Check the network and CUDA memory before enabling live CCTV.'
