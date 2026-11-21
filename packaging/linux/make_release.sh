#!/usr/bin/env bash
# Lay out what a person downloads, and pack it.
#
# The bundle on its own is not it. install.sh reads the desktop entry and the AppStream metadata
# from beside itself, so an archive holding only the bundle can be run and cannot be installed:
# the instructions would send somebody to a path that exists in a clone of this repository and
# nowhere on their machine. Whatever the tarball is supposed to let people do has to be inside it.
#
#     packaging/linux/make_release.sh <bundle dir> <output dir> [version]
#
# leaves <output dir>/firmauy-desktop-<version>-linux-x86_64.tar.gz, and the directory it was
# built from beside it.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
APP_ID="com.firmauy.firmauydesktop"

bundle="${1:?uso: make_release.sh <directorio del bundle> <directorio de salida> [versión]}"
out="${2:?falta el directorio de salida}"
version="${3:-}"

if [ -z "$version" ]; then
    # From the package rather than from a literal here, and a test holds that string equal to the
    # two other places it appears. One more copy of a version is one more thing to forget.
    version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$repo/src/firmauy_desktop/__init__.py")
fi
[ -n "$version" ] || { echo "error: no pude leer la versión" >&2; exit 1; }

name="firmauy-desktop-$version-linux-x86_64"
stage="$out/$name"

rm -rf "$stage"
install -d "$stage"
cp -a "$bundle" "$stage/firmauy-desktop"

install -m 755 "$here/install.sh" "$here/uninstall.sh" "$stage/"
install -m 644 "$here/$APP_ID.desktop" "$here/$APP_ID.metainfo.xml" "$stage/"
install -m 644 "$repo/LICENSE" "$stage/"

# Read by whoever unpacks this and looks for the next step, which is the one moment the answer
# has to be in the archive rather than in a repository they may not have.
cat > "$stage/LEEME.txt" <<TXT
FirmaUY Desktop $version, Linux x86_64

Correrlo tal cual, sin instalar nada:

    ./firmauy-desktop/firmauy-desktop

Instalarlo, para que aparezca en el menú con su icono:

    ./install.sh firmauy-desktop                   # para tu usuario, sin root
    sudo ./install.sh firmauy-desktop --system     # para toda la máquina

Sacarlo:

    ./uninstall.sh
    sudo ./uninstall.sh --system

Desinstalar no toca tus ajustes ni el registro de actividad, y te dice dónde quedaron.

Necesitás pcscd corriendo y un lector de tarjetas. El resto viene adentro.
Construido sobre glibc 2.35, así que distribuciones más viejas que esa no están soportadas.

Las licencias de lo que el programa trae de otros proyectos, Qt entre ellos, están
en firmauy-desktop/THIRD-PARTY-NOTICES.txt.

https://github.com/carlosplanchon/firmauy-desktop
TXT

# Recorded as root's, by number. Somebody unpacking this as themselves owns what comes out whatever
# it says, since tar cannot give files away. Unpacking as root, GNU tar restores the owner the
# archive names, and a plain tar names whoever built it: on CI the runner's uid, which on another
# machine is whichever account happens to have that number, holding a tree that install.sh
# --system then puts in /opt for root and everybody else to run.
tar --owner=0 --group=0 --numeric-owner -C "$out" -czf "$out/$name.tar.gz" "$name"

# Beside the archive and covering only its own name, so it can be checked from the directory it
# was downloaded into. What it is worth depends on where it was read from: a digest served next to
# the file it describes proves the download was not corrupted and nothing about who built it. The
# thing that would is a signature, and there is no key for one yet.
( cd "$out" && sha256sum "$name.tar.gz" > "$name.tar.gz.sha256" )

echo "$out/$name.tar.gz"
