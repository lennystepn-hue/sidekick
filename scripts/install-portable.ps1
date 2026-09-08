# Builds Sidekick (release exe + packaged sidecar), copies it to a per-user program folder
# and puts two shortcuts on the desktop:
#   "Sidekick"              starts the app (a second click just focuses the running instance)
#   "Sidekick neu starten"  ends running Sidekick/sidecar processes and starts fresh
#
#   pwsh scripts/install-portable.ps1                 # full build + install
#   pwsh scripts/install-portable.ps1 -SkipBuild      # reuse src-tauri/target/release/sidekick.exe
#   pwsh scripts/install-portable.ps1 -SkipSidecar    # reuse src-tauri/binaries/
param(
    [switch]$SkipBuild,
    [switch]$SkipSidecar,
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Programs\Sidekick")
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $repo
try {
    if (-not $SkipSidecar) {
        Write-Host "== Sidecar (PyInstaller) =="
        pwsh -NoProfile -File (Join-Path $repo "sidecar\tools\build_sidecar.ps1") -SkipTest
        if ($LASTEXITCODE -ne 0) { throw "sidecar build failed" }
    }
    if (-not $SkipBuild) {
        Write-Host "== App (pnpm tauri build --no-bundle) =="
        pnpm tauri build --no-bundle
        if ($LASTEXITCODE -ne 0) { throw "tauri build failed" }
    }

    $exe = Join-Path $repo "src-tauri\target\release\sidekick.exe"
    $sidecarExe = Get-ChildItem (Join-Path $repo "src-tauri\binaries") -Filter "sidekick-sidecar-*.exe" | Select-Object -First 1
    $internal = Join-Path $repo "src-tauri\binaries\_internal"
    foreach ($p in @($exe, $internal)) { if (-not (Test-Path $p)) { throw "missing $p" } }
    if (-not $sidecarExe) { throw "missing staged sidecar exe in src-tauri/binaries" }

    Write-Host "== Installing into $InstallDir =="
    $running = Get-Process -Name "sidekick", "sidekick-sidecar" -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$InstallDir*" }
    if ($running) {
        Write-Host "stopping running installed instance"
        $running | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
    New-Item -ItemType Directory -Force $InstallDir | Out-Null
    Copy-Item $exe (Join-Path $InstallDir "sidekick.exe") -Force
    # The windows-gnu build links WebView2Loader.dll dynamically; it must sit next to the exe.
    Get-ChildItem (Split-Path $exe) -Filter "*.dll" | ForEach-Object { Copy-Item $_.FullName (Join-Path $InstallDir $_.Name) -Force }
    Copy-Item $sidecarExe.FullName (Join-Path $InstallDir "sidekick-sidecar.exe") -Force
    $target = Join-Path $InstallDir "_internal"
    if (Test-Path $target) { Remove-Item -Recurse -Force $target }
    Copy-Item $internal $target -Recurse -Force

    $restart = Join-Path $InstallDir "Sidekick neu starten.cmd"
    @'
@echo off
rem Ends every running Sidekick (dev and installed) plus sidecar and starts the installed app.
taskkill /IM sidekick.exe /T /F >nul 2>&1
taskkill /IM sidekick-sidecar.exe /T /F >nul 2>&1
timeout /t 1 /nobreak >nul
start "" "%~dp0sidekick.exe"
'@ | Set-Content -Path $restart -Encoding ASCII

    Write-Host "== Desktop shortcuts =="
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut((Join-Path $desktop "Sidekick.lnk"))
    $lnk.TargetPath = (Join-Path $InstallDir "sidekick.exe")
    $lnk.WorkingDirectory = $InstallDir
    $lnk.IconLocation = (Join-Path $InstallDir "sidekick.exe") + ",0"
    $lnk.Description = "Sidekick: Ray-Ban Meta Companion fuer Claude Code"
    $lnk.Save()
    $lnk2 = $shell.CreateShortcut((Join-Path $desktop "Sidekick neu starten.lnk"))
    $lnk2.TargetPath = "$env:WINDIR\System32\cmd.exe"
    $lnk2.Arguments = "/c `"$restart`""
    $lnk2.WorkingDirectory = $InstallDir
    $lnk2.WindowStyle = 7
    $lnk2.IconLocation = (Join-Path $InstallDir "sidekick.exe") + ",0"
    $lnk2.Description = "Beendet laufende Sidekick-Instanzen und startet die App neu"
    $lnk2.Save()

    $size = [math]::Round(((Get-ChildItem $InstallDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB), 0)
    Write-Host "installed ($size MB): $InstallDir"
    Write-Host "shortcuts: $(Join-Path $desktop 'Sidekick.lnk'), $(Join-Path $desktop 'Sidekick neu starten.lnk')"
}
finally {
    Pop-Location
}
