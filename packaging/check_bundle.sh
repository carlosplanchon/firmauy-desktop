#!/usr/bin/env bash
# Everything asked of a built bundle, in one place so it can be asked twice.
#
# Once of the tree PyInstaller wrote, and once of the tree that comes back out of the archive
# people actually download. Those are not the same object and the difference is not academic:
# a GitHub artifact is a zip, and upload-artifact documents that zipped uploads do not preserve
# permissions, handing back directories at 755 and every file at 644. Measured on this bundle:
# 212 files carry the executable bit and 43 entries are symbolic links, which PyInstaller's own
# notes say a distribution format has to preserve for a onedir build. So the archive is a tarball
# and this script is run against what unpacking it produces.
#
#     packaging/check_bundle.sh <bundle root> <fixture dir>
set -euo pipefail

root="${1:?uso: check_bundle.sh <raíz del bundle> <directorio de la fixture>}"
fixture="${2:?falta el directorio de la fixture}"
exe="$root/firmauy-desktop"

# The two properties an archive can quietly destroy, checked before anything is run, because the
# failure they cause otherwise is "permission denied" with no hint of why.
if [ ! -x "$exe" ]; then
    echo "::error::$exe no es ejecutable: el formato del archivo perdió los permisos"
    exit 1
fi

links=$(find "$root" -type l | wc -l)
if [ "$links" -eq 0 ]; then
    echo "::error::no quedó ningún symlink en $root: el formato del archivo los resolvió"
    exit 1
fi
echo "bundle: $links symlinks, ejecutable con permisos"

# A bundle missing Qt's svg plugin starts, builds every screen and draws nothing where the icons
# go, silently. Counting pixels is the only way to tell it from a working one.
"$exe" --selftest-icons

# Qt's own words in Spanish, the right-click menu of every field among them, come from a
# translation file found at run time. A bundle without it starts fine and is half in English.
"$exe" --selftest-translations

# The check that touches what the app is for. INDETERMINATE is the honest ceiling: a file earning
# VALID would have to reach the national anchors, which are pinned by fingerprint.
"$exe" --selftest-verify "$fixture/firmado.pdf" INDETERMINATE

# 124 means the event loop came up and stayed up. Construction only: a name resolved when a button
# is clicked still gets past this.
set +e
QT_QPA_PLATFORM=offscreen timeout 20 "$exe" >/dev/null 2>&1
rc=$?
set -e
if [ "$rc" -ne 124 ]; then
    echo "::error::el bundle salió con $rc en vez de seguir vivo (124 = sigue corriendo)"
    exit 1
fi
echo "bundle: la ventana abre y se queda"
