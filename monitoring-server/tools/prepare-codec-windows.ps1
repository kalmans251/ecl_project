# Windows PowerShell 5.1 compatible. No administrator installation or persistent PATH changes.
param([string]$ProjectDir = (Split-Path $PSScriptRoot -Parent), [string]$Skip = 'false')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
# Maven may inherit PowerShell 7's module path while launching Windows PowerShell 5.1.
# Load this host's own built-in modules rather than a different edition's modules.
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1') -Force
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Management\Microsoft.PowerShell.Management.psd1') -Force
if ($Skip -eq 'true') { exit 0 }
if (-not [Environment]::Is64BitOperatingSystem) { throw 'Codec2 requires Windows x64.' }
$revision = '3e347e0b70fc72af9357fbbd32b10a125321d6c5'
$toolHash = '7ac8f55befb93720f048f2c788704543fbc632c0164a8239ecbdefc9559481c5'
# Official release asset digest: https://github.com/skeeto/w64devkit/releases/tag/v2.5.0
$toolUrl = 'https://github.com/skeeto/w64devkit/releases/download/v2.5.0/w64devkit-x64-2.5.0.7z.exe'
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
$target = Join-Path $ProjectDir 'target'
$bundle = Join-Path $target 'native-resources'
$dllDir = Join-Path $bundle 'win32-x86-64'
$dll = Join-Path $dllDir 'codec2.dll'
$stamp = Join-Path $target 'codec-windows-stamp.json'
$recipe = "$revision/$toolHash/$((Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash)"
if ((Test-Path -LiteralPath $dll) -and (Test-Path -LiteralPath $stamp) -and
    (Test-Path -LiteralPath (Join-Path $bundle 'META-INF/codec2/LICENSE')) -and
    (Test-Path -LiteralPath (Join-Path $bundle 'META-INF/codec2/source/src/codec2.c'))) {
    try {
        $cached = Get-Content -LiteralPath $stamp -Raw | ConvertFrom-Json
        if ($cached.recipe -eq $recipe -and $cached.hash -eq (Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash) {
            Write-Host 'Codec2 Windows DLL ready (cached).'
            exit 0
        }
    } catch { Write-Host 'Rebuilding incomplete Codec2 cache.' }
}
Get-Command git -ErrorAction Stop | Out-Null
$cache = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'ecl-monitoring-tools'
New-Item -ItemType Directory -Force -Path $cache,$dllDir | Out-Null
# A per-user lock prevents concurrent Maven builds from extracting the same toolchain.
$lock = $null
$until = [DateTime]::UtcNow.AddMinutes(5)
while ($null -eq $lock) {
    try { $lock = [IO.File]::Open((Join-Path $cache 'prepare.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch [IO.IOException] {
        if ([DateTime]::UtcNow -gt $until) { throw 'Another Codec2 build is still running. Retry after it finishes.' }
        Start-Sleep -Seconds 1
    }
}
try {
    $archive = Join-Path $cache 'w64devkit-x64-2.5.0.7z.exe'
    $toolDir = Join-Path $cache 'w64devkit-2.5.0'
    $gcc = Join-Path $toolDir 'w64devkit\bin\gcc.exe'
    if (-not (Test-Path -LiteralPath $gcc)) {
        if (-not (Test-Path -LiteralPath $archive)) {
            Write-Host 'Downloading pinned portable compiler (~40 MB); first run only.'
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $partial = "$archive.partial"
            try {
                Invoke-WebRequest -UseBasicParsing -Uri $toolUrl -OutFile $partial
                if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $toolHash) { throw 'Compiler download SHA256 mismatch.' }
                Move-Item -LiteralPath $partial -Destination $archive -Force
            } finally { if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force } }
        }
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $toolHash) { throw "Compiler cache SHA256 mismatch. Remove $archive and retry." }
        New-Item -ItemType Directory -Force -Path $toolDir | Out-Null
        # Verified official 7-Zip self-extractor. Quoted output path supports spaces.
        $extract = Start-Process -FilePath $archive -ArgumentList @('-y', ('-o"' + $toolDir + '"')) -Wait -PassThru
        if ($extract.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $gcc)) { throw 'Portable compiler extraction failed.' }
    }
    $source = Join-Path $target 'codec-windows-source'
    if (-not (Test-Path -LiteralPath (Join-Path $source '.git'))) {
        & git clone --no-checkout https://github.com/meshtastic/codec2.git $source
        if ($LASTEXITCODE -ne 0) { throw 'Codec2 source download failed; check GitHub connectivity.' }
    }
    & git -C $source checkout --detach --force $revision
    if ($LASTEXITCODE -ne 0) { throw 'Pinned Codec2 source checkout failed.' }
    $actual = & git -C $source rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $actual.Trim() -ne $revision) { throw 'Unexpected Codec2 source revision.' }
    # Read only tracked C files; avoid accidentally compiling untracked files in the cache.
    $sources = @(& git -C $source ls-files 'src/*.c')
    if ($LASTEXITCODE -ne 0 -or $sources.Count -eq 0) { throw 'Codec2 source file list is empty.' }
    $tempDll = Join-Path $dllDir 'codec2-new.dll'
    $arguments = @('-shared','-O2','-std=gnu11','-fsingle-precision-constant','-static-libgcc',
        '-Wl,--export-all-symbols','-DCODEC2_MODE_EN_DEFAULT=0','-DCODEC2_MODE_2400_EN=1',
        '-I', (Join-Path $source 'src'), '-o', $tempDll)
    $arguments += @($sources | ForEach-Object { Join-Path $source $_ })
    $arguments += '-lm'
    # GCC response file avoids Windows command-line length and whitespace limits.
    $response = Join-Path $target 'codec-windows-args.txt'
    $lines = @($arguments | ForEach-Object { '"' + $_.Replace('\','/').Replace('"','\"') + '"' })
    [IO.File]::WriteAllLines($response, $lines, (New-Object Text.UTF8Encoding($false)))
    Write-Host 'Building firmware-pinned Codec2 2400 Windows DLL...'
    & $gcc "@$response"
    if ($LASTEXITCODE -ne 0) { throw 'Codec2 compile failed. Server startup stopped.' }
    Move-Item -LiteralPath $tempDll -Destination $dll -Force
    $licenseDir = Join-Path $bundle 'META-INF\codec2'
    New-Item -ItemType Directory -Force -Path (Join-Path $licenseDir 'source') | Out-Null
    Copy-Item -LiteralPath (Join-Path $source 'src') -Destination (Join-Path $licenseDir 'source') -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $source 'LICENSE') -Destination $licenseDir -Force
    Copy-Item -LiteralPath (Join-Path $ProjectDir 'native\NOTICE.md') -Destination $licenseDir -Force
    Copy-Item -LiteralPath $PSCommandPath -Destination $licenseDir -Force
    @{recipe=$recipe;hash=(Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash} | ConvertTo-Json | Set-Content -LiteralPath $stamp
    Write-Host 'Codec2 Windows DLL built and bundled successfully.'
} finally { if ($null -ne $lock) { $lock.Dispose() } }
