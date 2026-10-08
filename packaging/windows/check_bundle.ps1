# Everything asked of a built Windows bundle, in one place so it can be asked more than once.
#
# The Windows half of packaging/check_bundle.sh, and the same questions in the same order. What it
# leaves out is what cannot go wrong here: a zip of this tree keeps everything a onedir build needs,
# because a Windows bundle has no executable bit to lose and no symbolic links to resolve. So it is
# asked of the tree PyInstaller wrote, of the tree that comes back out of the zip people download,
# and of the tree the installer puts on disk.
#
#     packaging/windows/check_bundle.ps1 -Root <bundle root> -Fixture <fixture dir> [-Version x.y.z]
#
# Windows PowerShell 5.1 and PowerShell 7 alike: the first is what a person has, the second is what
# a GitHub runner uses for `shell: pwsh`.
param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$Fixture,
    [string]$Version = ""
)
$ErrorActionPreference = "Stop"

$exe = Join-Path $Root "firmauy-desktop.exe"
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    Write-Output "::error::no hay $exe"
    exit 1
}

# The resource Explorer and Task Manager read. Asked only when the caller knows what to expect,
# since this script has no repository to read a version from when it runs on an unpacked download.
if ($Version) {
    $declared = (Get-Item -LiteralPath $exe).VersionInfo.ProductVersion
    if ($declared -ne $Version) {
        Write-Output "::error::el .exe dice que es la versión '$declared' y se esperaba '$Version'"
        exit 1
    }
    Write-Output "bundle: el .exe declara la versión $declared"
}

# A GUI-subsystem executable does not hold the console: PowerShell launches it and moves on, so
# `& $exe` would report the exit code of nothing. Start-Process -Wait is what waits for it, and
# the redirection is what brings back the line each self-test prints. Arguments are quoted by
# hand, because Start-Process joins them with spaces and the fixture lives under a path that may
# have some.
$ansi = [Text.Encoding]::GetEncoding([Globalization.CultureInfo]::CurrentCulture.TextInfo.ANSICodePage)

function Invoke-Selftest([string[]]$Arguments) {
    $out = [IO.Path]::GetTempFileName()
    $err = [IO.Path]::GetTempFileName()
    try {
        $quoted = $Arguments | ForEach-Object { '"' + $_ + '"' }
        $p = Start-Process -FilePath $exe -ArgumentList $quoted -Wait -PassThru -NoNewWindow `
            -RedirectStandardOutput $out -RedirectStandardError $err
        # Python writes a redirected stream in the ANSI code page, so that is how it is read back.
        foreach ($file in $out, $err) {
            $text = [IO.File]::ReadAllText($file, $ansi).TrimEnd()
            if ($text) { $text }
        }
        if ($p.ExitCode -ne 0) {
            Write-Output "::error::$($Arguments[0]) salió con $($p.ExitCode)"
            exit 1
        }
    } finally {
        Remove-Item -LiteralPath $out, $err -ErrorAction SilentlyContinue
    }
}

# A bundle missing Qt's svg plugin starts, builds every screen and draws nothing where the icons
# go, silently. Counting pixels is the only way to tell it from a working one.
Invoke-Selftest @("--selftest-icons")

# Qt's own words in Spanish, the right-click menu of every field among them, come from a
# translation file found at run time. A bundle without it starts fine and is half in English.
Invoke-Selftest @("--selftest-translations")

# The check that touches what the app is for. INDETERMINATE is the honest ceiling: a file earning
# VALID would have to reach the national anchors, which are pinned by fingerprint.
Invoke-Selftest @("--selftest-verify", (Join-Path $Fixture "firmado.pdf"), "INDETERMINATE")

# The window comes up and stays up. Construction only: a name resolved when a button is clicked
# still gets past this. Offscreen like the Linux check, so a runner with no one logged in to its
# desktop answers the same question.
$previous = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = "offscreen"
try {
    $p = Start-Process -FilePath $exe -PassThru -NoNewWindow
    if ($p.WaitForExit(20000)) {
        Write-Output "::error::el bundle salió con $($p.ExitCode) en vez de seguir vivo"
        exit 1
    }
    Stop-Process -Id $p.Id -Force
} finally {
    $env:QT_QPA_PLATFORM = $previous
}
Write-Output "bundle: la ventana abre y se queda"
# Said out loud, so a caller reading $LASTEXITCODE gets 0 rather than whatever was there before:
# nothing native ran last, and without this it would be stale or $null.
exit 0
