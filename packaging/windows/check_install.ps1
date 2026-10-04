# Install what somebody downloaded, upgrade it, and take it away again.
#
# The Windows half of packaging/linux/check_install.sh, holding the same things: that an installed
# shortcut points at something that exists and works, that a second install leaves the new bundle
# and not the union of both, and that uninstalling removes what was installed and leaves the
# person's settings alone.
#
# Per user, the installer's default, and into a directory of its own, so a machine that already has
# the app installed is not the one being upgraded. The Start menu shortcut and the uninstall entry
# are the real ones, though, since that is what is being checked: run it where those are yours to
# overwrite, which a CI runner is.
#
#     packaging/windows/check_install.ps1 -Setup <...-setup.exe> -Fixture <fixture dir>
param(
    [Parameter(Mandatory = $true)][string]$Setup,
    [Parameter(Mandatory = $true)][string]$Fixture
)
$ErrorActionPreference = "Stop"

$APP_ID = "com.firmauy.firmauydesktop"
$Setup = (Resolve-Path $Setup).Path
$base = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$dir = Join-Path $base ("firmauy-install-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
$exe = Join-Path $dir "firmauy-desktop.exe"
$shortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "FirmaUY Desktop.lnk"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}_is1"

function Fail([string]$Message) {
    Write-Output "::error::$Message"
    exit 1
}

function Install {
    $log = Join-Path $base "firmauy-setup.log"
    $p = Start-Process -FilePath $Setup -Wait -PassThru -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", "/DIR=`"$dir`"",
        "/LOG=`"$log`"")
    if ($p.ExitCode -ne 0) {
        Get-Content -LiteralPath $log -ErrorAction SilentlyContinue | Select-Object -Last 30
        Fail "el instalador salió con $($p.ExitCode)"
    }
}

Install

if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { Fail "no quedó $exe" }
if (-not (Test-Path -LiteralPath $shortcut)) { Fail "no se creó el acceso en el menú Inicio" }

# The shortcut has to point at something that exists, which is the failure nobody sees: a Start
# menu entry that resolves to nothing reports nothing, it just does not start.
$target = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut).TargetPath
if ((Resolve-Path -LiteralPath $target).Path -ne (Resolve-Path -LiteralPath $exe).Path) {
    Fail "el acceso apunta a $target y no a $exe"
}
if (-not (Get-ItemProperty -Path $uninstallKey -ErrorAction SilentlyContinue)) {
    Fail "no quedó la entrada de desinstalación ($uninstallKey)"
}

# The installed tree is a third copy of the bundle, after the one PyInstaller wrote and the one in
# the zip, and it is the one people run.
# Read as a number on purpose: $null -ne 0 is true in PowerShell, and an earlier version of this
# line took that for a failure and stopped here, half installed, reporting success.
& (Join-Path $PSScriptRoot "check_bundle.ps1") -Root $dir -Fixture $Fixture
if ([int]$LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output "instalación: ejecutable, acceso en el menú Inicio y desinstalador en su lugar"

# An upgrade has to produce the new bundle, not the new one on top of the old one. _internal\ is
# where the DLLs and the Qt plugins live, so a leftover there is a library from a previous release
# sitting next to the current ones.
$ghost = Join-Path $dir "_internal\de-una-version-anterior.dll"
Set-Content -LiteralPath $ghost -Value "restos"
Install
if (Test-Path -LiteralPath $ghost) { Fail "reinstalar dejó archivos de la instalación anterior" }
if (-not (Test-Path -LiteralPath $exe)) { Fail "reinstalar se llevó el ejecutable" }
Write-Output "actualización: el bundle nuevo reemplaza al anterior"

# Something of the person's, where the app keeps it, to prove uninstalling does not touch it.
$settingsKey = "HKCU:\Software\firmauy\FirmaUY Desktop"
$hadSettings = Test-Path -Path $settingsKey
if (-not $hadSettings) { New-Item -Path $settingsKey -Force | Out-Null }
Set-ItemProperty -Path $settingsKey -Name "check_install" -Value "sigue acá"

# Inno's uninstaller copies itself to a temporary directory and returns before the copy is done,
# so its exit is not the end of the uninstall. The files going is.
$uninstaller = Get-ChildItem -LiteralPath $dir -Filter "unins*.exe" | Select-Object -First 1
if (-not $uninstaller) { Fail "no hay desinstalador en $dir" }
Start-Process -FilePath $uninstaller.FullName -Wait -ArgumentList @(
    "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
$deadline = (Get-Date).AddSeconds(60)
while ((Test-Path -LiteralPath $exe) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }

if (Test-Path -LiteralPath $exe) { Fail "desinstalar dejó $exe" }
if (Test-Path -LiteralPath (Join-Path $dir "_internal")) { Fail "desinstalar dejó _internal" }
if (Test-Path -LiteralPath $shortcut) { Fail "desinstalar dejó el acceso en el menú Inicio" }
if (Get-ItemProperty -Path $uninstallKey -ErrorAction SilentlyContinue) {
    Fail "desinstalar dejó la entrada en Agregar o quitar programas"
}
$kept = (Get-ItemProperty -Path $settingsKey -ErrorAction SilentlyContinue).check_install
if ($hadSettings) {
    Remove-ItemProperty -Path $settingsKey -Name "check_install"
} else {
    Remove-Item -Path "HKCU:\Software\firmauy" -Recurse -Force
}
if ($kept -ne "sigue acá") { Fail "desinstalar se llevó los ajustes de la persona" }
Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
Write-Output "desinstalación: se fue lo instalado, los ajustes quedaron"
