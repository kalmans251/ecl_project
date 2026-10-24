$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$originalPath = $env:PATH
# GitHub runners have unrelated MinGW tools installed. Hide them to match user PCs.
$gitBin = Split-Path (Get-Command git.exe).Source -Parent
$javaBin = Split-Path (Get-Command java.exe).Source -Parent
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$PSHOME;$gitBin;$javaBin"
try {
if (Get-Command as.exe -ErrorAction SilentlyContinue) { throw 'Test PATH unexpectedly contains an assembler' }
$probe = Join-Path $project 'target\probe with spaces'
New-Item -ItemType Directory -Force -Path (Join-Path $probe 'native') | Out-Null
Copy-Item (Join-Path $project 'native\NOTICE.md') (Join-Path $probe 'native')
$script = Join-Path $PSScriptRoot 'prepare-codec-windows.ps1'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -ProjectDir $probe
if ($LASTEXITCODE -ne 0) { throw 'Preparation with spaces failed' }
$dll = Join-Path $probe 'target\native-resources\win32-x86-64\codec2.dll'
$before = (Get-Item $dll).LastWriteTimeUtc
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -ProjectDir $probe
if ($LASTEXITCODE -ne 0 -or (Get-Item $dll).LastWriteTimeUtc -ne $before) { throw 'Cache was not reused' }
[IO.File]::WriteAllText($dll, 'corrupted')
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -ProjectDir $probe
if ($LASTEXITCODE -ne 0 -or (Get-Item $dll).Length -lt 1000) { throw 'Corrupt DLL was not rebuilt' }
$previous = $env:CODEC2_LIBRARY
try {
    $env:CODEC2_LIBRARY = $dll
    & java -jar (Join-Path $project 'target\monitoring-server-0.1.0.jar') --codec-self-test
    if ($LASTEXITCODE -ne 0) { throw 'Rebuilt DLL self-test failed' }
} finally { $env:CODEC2_LIBRARY = $previous }

} finally { $env:PATH = $originalPath }
