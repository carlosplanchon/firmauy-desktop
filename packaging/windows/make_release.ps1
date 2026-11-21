# Lay out what a person on Windows downloads, and pack it, twice over.
#
# The Windows half of packaging/linux/make_release.sh. Two artifacts instead of one, because
# Windows has two habits and each one is somebody's:
#
#   firmauy-desktop-<v>-windows-x86_64.zip        unzip and run, nothing written anywhere else
#   firmauy-desktop-<v>-windows-x86_64-setup.exe  Start menu, uninstaller, upgrades in place
#
# A zip is the right archive here, where on Linux it was the wrong one: a Windows onedir bundle has
# no executable bit to lose and no symbolic links to resolve. Each gets a .sha256 beside it in the
# format `sha256sum -c` reads, since that is what the publish job, on Linux, checks them with.
#
#     packaging/windows/make_release.ps1 -Bundle <bundle dir> -Out <output dir> [-Version x.y.z]
#         [-Iscc <path to ISCC.exe>]
param(
    [Parameter(Mandatory = $true)][string]$Bundle,
    [Parameter(Mandatory = $true)][string]$Out,
    [string]$Version = "",
    [string]$Iscc = ""
)
$ErrorActionPreference = "Stop"

$here = $PSScriptRoot
$repo = (Resolve-Path (Join-Path $here "..\..")).Path
$Bundle = (Resolve-Path $Bundle).Path
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Out = (Resolve-Path $Out).Path

if (-not $Version) {
    # From the package rather than from a literal here, as make_release.sh does. One more copy of
    # a version is one more thing to forget.
    $init = Get-Content -LiteralPath (Join-Path $repo "src\firmauy_desktop\__init__.py") -Raw
    if ($init -match '(?m)^__version__ = "([^"]+)"') { $Version = $Matches[1] }
}
if (-not $Version) { throw "no pude leer la versión" }

if (-not $Iscc) {
    $found = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $candidates = @(
        $(if ($found) { $found.Source }),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $Iscc = $candidates | Select-Object -First 1
}
if (-not $Iscc) { throw "no encuentro ISCC.exe (Inno Setup 6). Pasalo con -Iscc." }

$name = "firmauy-desktop-$Version-windows-x86_64"
$stage = Join-Path $Out $name
if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null
Copy-Item -LiteralPath $Bundle -Destination (Join-Path $stage "firmauy-desktop") -Recurse
Copy-Item -LiteralPath (Join-Path $repo "LICENSE") -Destination (Join-Path $stage "LICENSE.txt")

# Read by whoever unzips this and looks for the next step. CRLF, because Notepad is what opens it.
$leeme = @"
FirmaUY Desktop $Version, Windows x64

Correrlo tal cual, sin instalar nada:

    firmauy-desktop\firmauy-desktop.exe

Si preferís que aparezca en el menú Inicio, con desinstalador, bajá el instalador
($name-setup.exe) en lugar de este zip.

Necesitás un lector de tarjetas. Windows trae el driver y el servicio de tarjeta
inteligente, así que en modo directo no hay nada más que instalar. Thales Classic
Client hace falta solo para el modo PKCS#11 o la pantalla Avanzado.

Windows puede avisar que protegió tu equipo: el programa todavía no está firmado
con un certificado de código. "Más información" y después "Ejecutar de todas formas".
Si tenés activado Smart App Control ("Control inteligente de aplicaciones"), esa
opción no aparece: Windows lo bloquea y no deja hacer una excepción para un
programa puntual. Hasta que esté firmado, con esa protección activada no corre.

Para comprobar que el archivo salió del repositorio y no de otro lado:

    gh attestation verify $name.zip -R carlosplanchon/firmauy-desktop

Tus ajustes quedan en el registro (HKCU\Software\firmauy) y el registro de
actividad, si lo activás, en %LOCALAPPDATA%\firmauy. Borrar esta carpeta no los toca.

Las licencias de lo que el programa trae de otros proyectos, Qt entre ellos, están
en firmauy-desktop\THIRD-PARTY-NOTICES.txt.

https://github.com/carlosplanchon/firmauy-desktop
"@
[IO.File]::WriteAllText((Join-Path $stage "LEEME.txt"), ($leeme -replace "`r?`n", "`r`n"),
    (New-Object Text.UTF8Encoding $true))

# bsdtar, which ships with Windows 10 and later, rather than Compress-Archive: Windows PowerShell
# 5.1's Compress-Archive writes entry names with backslashes, which other unzippers read as one
# long file name, and it is slow on a few thousand files.
$zip = "$name.zip"
Remove-Item -LiteralPath (Join-Path $Out $zip) -ErrorAction SilentlyContinue
& "$env:SystemRoot\System32\tar.exe" -a -c -f (Join-Path $Out $zip) -C $Out $name
if ($LASTEXITCODE -ne 0) { throw "tar salió con $LASTEXITCODE" }

$setup = "$name-setup.exe"
& $Iscc /Q "/DAppVersion=$Version" "/DBundleDir=$Bundle" "/O$Out" (Join-Path $here "firmauy-desktop.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC salió con $LASTEXITCODE" }
if (-not (Test-Path -LiteralPath (Join-Path $Out $setup))) { throw "ISCC no dejó $setup" }

# "<digest>  <name>", lowercase, LF and no BOM: the exact line sha256sum writes and reads. What it
# is worth is what the Linux one is worth: it proves the download was not corrupted, and nothing
# about who built it. The attestation says that, and a code-signing certificate would.
foreach ($file in $zip, $setup) {
    $digest = (Get-FileHash -LiteralPath (Join-Path $Out $file) -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText((Join-Path $Out "$file.sha256"), "$digest  $file`n",
        (New-Object Text.UTF8Encoding $false))
}

Write-Output "release: $zip, $setup"
