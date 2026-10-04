#!/usr/bin/env bash
# Install what somebody downloaded, upgrade it, and take it away again.
#
# Run against an unpacked release directory, with a throwaway HOME, so nothing here touches the
# machine it runs on. What it holds is the half of distribution that the bundle checks cannot see:
# that the archive carries the things its own instructions name, that an installed entry points at
# something that exists, that a second install leaves the new bundle and not the union of both,
# and that removing it removes it.
#
#     packaging/linux/check_install.sh <directorio de release desempaquetado>
set -euo pipefail

release="${1:?uso: check_install.sh <directorio de release desempaquetado>}"
APP_ID="com.firmauy.firmauydesktop"

fake="$(mktemp -d)"
trap 'rm -rf "$fake"' EXIT
export HOME="$fake"
unset XDG_DATA_HOME          # so this exercises the default branch, as most machines do

fail() { echo "::error::$1"; exit 1; }

# What the archive has to carry. The instructions inside it name each of these, and a person who
# only has the download has no other copy of any of them.
for needed in install.sh uninstall.sh "$APP_ID.desktop" "$APP_ID.metainfo.xml"; do
    [ -f "$release/$needed" ] || fail "el release no trae $needed, así que no se puede instalar"
done
[ -x "$release/install.sh" ] || fail "install.sh no quedó ejecutable dentro del release"

"$release/install.sh" "$release/firmauy-desktop" >/dev/null

opt="$HOME/.local/opt/firmauy-desktop"
share="$HOME/.local/share"
entry="$share/applications/$APP_ID.desktop"

[ -x "$HOME/.local/bin/firmauy-desktop" ] || fail "el lanzador no quedó ejecutable"
[ -f "$entry" ] || fail "no se instaló la entrada de escritorio"
[ -f "$share/icons/hicolor/scalable/apps/$APP_ID.svg" ] || fail "falta el SVG"
[ -f "$share/icons/hicolor/512x512/apps/$APP_ID.png" ] || fail "falta el PNG"
[ -f "$share/metainfo/$APP_ID.metainfo.xml" ] || fail "falta el metainfo"

# The entry has to point at something that exists, which is the failure nobody sees: a menu item
# that resolves to nothing does not report anything, it just does not start.
target=$(sed -n 's/^Exec=//p' "$entry")
[ -x "$target" ] || fail "Exec= apunta a $target, que no es ejecutable"

[ "$(find "$opt" -type l | wc -l)" -gt 0 ] || fail "la instalación resolvió los symlinks"

QT_QPA_PLATFORM=offscreen "$target" --selftest-icons >/dev/null \
    || fail "lo instalado no dibuja sus iconos"
echo "instalación: entrada, iconos, metainfo y lanzador en su lugar"

# An upgrade has to produce the new bundle, not the new one on top of the old one. _internal/ is
# where the shared libraries and the Qt plugins live, so a leftover there is a library from a
# previous release sitting next to the current ones.
ghost="$opt/_internal/de-una-version-anterior.so"
echo "restos" > "$ghost"
"$release/install.sh" "$release/firmauy-desktop" >/dev/null
[ ! -e "$ghost" ] || fail "reinstalar dejó archivos de la instalación anterior"
[ -x "$HOME/.local/bin/firmauy-desktop" ] || fail "reinstalar rompió el lanzador"
echo "actualización: el árbol quedó exactamente el nuevo"

"$release/uninstall.sh" >/dev/null
left=$(find "$HOME" -name "*firmauy*" -not -path "*/.config/*" -not -path "*/.local/state/*" 2>/dev/null)
[ -z "$left" ] || fail "quedó esto después de desinstalar: $left"
echo "desinstalación: no quedó nada"

# The branch the run above never takes. A desktop reads XDG_DATA_HOME when it is set, so writing
# to ~/.local/share regardless puts the entry where nothing is looking, on exactly the machines
# whose owner went and configured this.
export XDG_DATA_HOME="$fake/datos elegidos"
"$release/install.sh" "$release/firmauy-desktop" >/dev/null
[ -f "$XDG_DATA_HOME/applications/$APP_ID.desktop" ] \
    || fail "con XDG_DATA_HOME puesto, la entrada no fue a parar ahí"
[ ! -e "$HOME/.local/share/applications/$APP_ID.desktop" ] \
    || fail "escribió igual en ~/.local/share, ignorando XDG_DATA_HOME"
"$release/uninstall.sh" >/dev/null
[ ! -e "$XDG_DATA_HOME/applications/$APP_ID.desktop" ] \
    || fail "desinstalar no miró XDG_DATA_HOME, así que dejó la entrada"
unset XDG_DATA_HOME
echo "XDG_DATA_HOME: instalar y desinstalar van al mismo lugar"

# A home directory is a person's to name, and the path lands inside the desktop entry. The value
# used to be spliced in with sed: measured, "&" made sed substitute the whole match and write a
# corrupted path while exiting 0, "|" broke the delimiter, and a space produced an Exec the
# specification calls invalid because reserved characters have to be quoted.
for odd in "con espacios" "con&ampersand" "con|pipe" "con\$dolar" 'con`backtick`'; do
    hostile="$fake/hostil/$odd"
    rm -rf "$hostile"; mkdir -p "$hostile"
    HOME="$hostile" "$release/install.sh" "$release/firmauy-desktop" >/dev/null \
        || fail "instalar falló con un HOME que tiene: $odd"
    entry="$hostile/.local/share/applications/$APP_ID.desktop"
    desktop-file-validate "$entry" || fail "la entrada quedó inválida con un HOME: $odd"
    target=$(sed -n 's/^Exec=//p' "$entry" | sed 's/^"//; s/"$//; s/\\\(.\)/\1/g')
    [ -x "$target" ] || fail "con un HOME que tiene $odd, Exec apunta a $target"
done
export HOME="$fake"
echo "HOME poco convencional: la entrada sigue siendo válida y ejecutable"

# The --system branch, only where the machine is as disposable as the HOME above: it writes to
# /opt and /usr/local and it needs root, so the workflows ask for it and nobody's own machine runs
# it by accident. What it holds is who owns the result. The release was unpacked here by an
# ordinary user, as it is by whoever downloads it, and cp -a kept that owner all the way into
# /opt: a program that root and every other account run, and that one account could rewrite.
if [ "${CHECK_SYSTEM_INSTALL:-}" = "1" ]; then
    if "$release/install.sh" "$release/firmauy-desktop" --system >/dev/null 2>&1; then
        fail "install.sh --system corrió sin root"
    fi
    [ ! -e /opt/firmauy-desktop ] || fail "install.sh --system escribió en /opt antes de negarse"

    sudo "$release/install.sh" "$release/firmauy-desktop" --system >/dev/null
    foreign=$(find /opt/firmauy-desktop \( ! -user root -o ! -group root \) -print | head -5)
    [ -z "$foreign" ] || fail "en /opt quedaron archivos que no son de root: $foreign"
    writable=$(find /opt/firmauy-desktop ! -type l -perm /022 -print | head -5)
    [ -z "$writable" ] || fail "en /opt quedaron archivos que otros pueden escribir: $writable"
    QT_QPA_PLATFORM=offscreen /usr/local/bin/firmauy-desktop --selftest-icons >/dev/null \
        || fail "lo instalado en /opt no dibuja sus iconos"

    sudo "$release/uninstall.sh" --system >/dev/null
    [ ! -e /opt/firmauy-desktop ] || fail "desinstalar --system dejó /opt/firmauy-desktop"
    [ ! -e /usr/local/bin/firmauy-desktop ] || fail "desinstalar --system dejó el lanzador"
    echo "--system: todo lo que queda en /opt es de root, y nadie más puede escribirlo"
fi
