# Builds the Python sidecar with PyInstaller and stages it for the Tauri bundler.
#
#   pwsh sidecar/tools/build_sidecar.ps1            # build + stage + smoke test
#   pwsh sidecar/tools/build_sidecar.ps1 -SkipTest
#
# Output: src-tauri/binaries/sidekick-sidecar-<triple>.exe (msvc and gnu) + src-tauri/binaries/_internal/
param(
    [switch]$SkipTest,
    [int]$TestPort = 47899
)

$ErrorActionPreference = "Stop"
$sidecar = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$repo = Split-Path -Parent $sidecar
$dist = Join-Path $sidecar "dist\sidekick-sidecar"
$target = Join-Path $repo "src-tauri\binaries"

Push-Location $sidecar
try {
    Write-Host "== PyInstaller build =="
    uv run pyinstaller tools/sidecar.spec --noconfirm --clean --distpath dist --workpath build
    if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed with exit code $LASTEXITCODE" }

    Write-Host "== Staging into $target =="
    New-Item -ItemType Directory -Force $target | Out-Null
    if (Test-Path (Join-Path $target "_internal")) { Remove-Item -Recurse -Force (Join-Path $target "_internal") }
    # Tauri looks for <name>-<target triple>.exe; stage both triples so msvc and gnu toolchains work.
    foreach ($triple in @("x86_64-pc-windows-msvc", "x86_64-pc-windows-gnu")) {
        Copy-Item (Join-Path $dist "sidekick-sidecar.exe") (Join-Path $target "sidekick-sidecar-$triple.exe") -Force
    }
    Copy-Item (Join-Path $dist "_internal") (Join-Path $target "_internal") -Recurse -Force
    $size = [math]::Round(((Get-ChildItem $target -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB), 1)
    Write-Host "staged ($size MB)"

    if (-not $SkipTest) {
        Write-Host "== Smoke test on port $TestPort =="
        $exe = Join-Path $target "sidekick-sidecar-x86_64-pc-windows-msvc.exe"
        $proc = Start-Process -FilePath $exe -ArgumentList "--port", $TestPort, "--fake", "--log-level", "warning" -PassThru -WindowStyle Hidden
        $ok = $false
        for ($i = 0; $i -lt 40; $i++) {
            Start-Sleep -Milliseconds 500
            try {
                $r = Invoke-RestMethod -Uri "http://127.0.0.1:$TestPort/health" -TimeoutSec 2
                if ($r.ok) { $ok = $true; break }
            } catch {}
        }
        try { Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$TestPort/shutdown" -TimeoutSec 2 | Out-Null } catch {}
        Start-Sleep -Seconds 1
        if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
        if (-not $ok) { throw "packaged sidecar did not answer /health" }
        Write-Host "packaged sidecar answered /health: OK"
    }
}
finally {
    Pop-Location
}
