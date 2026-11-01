#!/usr/bin/env bash
# Put an unpacked bundle where the desktop can find it, and tell the desktop about it.
#
# The tarball on its own is a directory with a binary in it: double clicking the binary works,
# and nothing else does. No menu entry, no icon, no window matched to an application. This is the
# small amount of work that turns it into something installed.
#
# Nothing here needs root by default. A per-user install lands under ~/.local, which is where the
# XDG base directory specification puts a user's own data, and needs no package manager and no
# sudo. --system puts the bundle in /opt, which is the location FHS reserves for exactly this kind
# of self-contained add-on package, with the entry and the icons under /usr/local/share.
#
#     packaging/linux/install.sh <directorio del bundle> [--system]
#     packaging/linux/uninstall.sh [--system]
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="com.firmauy.firmauydesktop"

bundle="${1:?uso: install.sh <directorio del bundle> [--system]}"
mode="${2:-}"

if [ ! -x "$bundle/firmauy-desktop" ]; then
    echo "error: no hay un firmauy-desktop ejecutable en $bundle" >&2
    echo "       si lo bajaste como zip, los permisos se perdieron: usá el .tar.gz" >&2
    exit 1
fi

if [ "$mode" = "--system" ]; then
    # Asked before anything is written, so a run without root stops here instead of half way
    # through /usr/local with one permission error per directory.
    if [ "$(id -u)" -ne 0 ]; then
        echo "error: --system instala para toda la máquina y necesita root:" >&2
        printf '       sudo %q %q --system\n' "$0" "$bundle" >&2
        exit 1
    fi
    opt="/opt/firmauy-desktop"
    bin="/usr/local/bin"
    share="/usr/local/share"
else
    opt="$HOME/.local/opt/firmauy-desktop"
    bin="$HOME/.local/bin"
    # XDG_DATA_HOME when it is set, which is the variable a desktop actually reads to find
    # applications and icons. Writing to ~/.local/share regardless puts the entry somewhere
    # nothing is looking, on exactly the machines whose owner went and configured this.
    share="${XDG_DATA_HOME:-$HOME/.local/share}"
fi

install -d "$bin" "$share/applications" \
           "$share/icons/hicolor/scalable/apps" "$share/icons/hicolor/512x512/apps"

# Staged and swapped, not copied over. Copying leaves whatever the previous version put there:
# measured, a file dropped into _internal/ survived a reinstall, and _internal/ is where the
# shared libraries, the Qt plugins and the Python extensions live. An upgrade has to produce
# exactly the new bundle, not the new one with the leftovers of every older one underneath.
#
# -a rather than -r: the bundle carries 35 symbolic links and PyInstaller requires a onedir build
# to keep them, so a copy that resolves them produces a much larger directory that may not run.
staged="$opt.nuevo.$$"
previous="$opt.viejo.$$"
trap 'rm -rf "$staged" "$previous"' EXIT

rm -rf "$staged"
install -d "$staged"
cp -a "$bundle/." "$staged/"
[ -x "$staged/firmauy-desktop" ] || { echo "error: la copia no quedó ejecutable" >&2; exit 1; }

# A system install is root's, whoever unpacked it. cp -a keeps each file's owner, and the release
# is usually unpacked by the person who downloaded it, so /opt ended up theirs: a program every
# other account, root included, runs and that one account can rewrite. -h gives a symbolic link
# itself to root rather than following it to whatever it names, which need not be inside the
# bundle. go-w is the same rule by other means, since an umask at unpacking time can leave files
# writable by a group. Symbolic links have no mode of their own, and chmod -R does not follow them.
if [ "$mode" = "--system" ]; then
    chown -R -h 0:0 "$staged"
    chmod -R go-w "$staged"
fi

# The old tree is renamed aside rather than deleted first, so the window in which nothing is
# installed is one rename long instead of one recursive delete long.
[ -e "$opt" ] && mv "$opt" "$previous"
mv "$staged" "$opt"
rm -rf "$previous"
trap - EXIT

ln -sf "$opt/firmauy-desktop" "$bin/firmauy-desktop"

# Named after the application id, which is what the Icon= line in the entry refers to. hicolor is
# the fallback theme every icon theme inherits from, so this shows up whatever theme is in use.
assets="$opt/_internal/firmauy_desktop/assets"
install -m 644 "$assets/icon.svg" "$share/icons/hicolor/scalable/apps/$APP_ID.svg"
install -m 644 "$assets/icon.png" "$share/icons/hicolor/512x512/apps/$APP_ID.png"

# Exec becomes the launcher's real path. The file in this directory says plain "firmauy-desktop",
# which is right for a distribution package that puts the binary on PATH, and wrong here: a
# per-user install lands in ~/.local/bin, which plenty of systems do not have on PATH, and a menu
# entry that resolves to nothing fails with no message anybody can act on.
#
# Not with sed, and not unquoted. The path comes from $HOME, so it is not this script's text, and
# both mattered: measured, a home directory containing "&" made sed substitute the whole match and
# wrote a corrupted path while exiting 0, and one containing "|" broke the delimiter outright. A
# home with a space produced a syntactically invalid Exec, since the specification requires a value
# holding reserved characters to be quoted.
#
# The safe set is deliberately small: anything outside it gets quoted rather than reasoned about.
# Inside double quotes the specification asks for a backslash, a double quote, a backtick and a
# dollar to be escaped, and the order below matters, since escaping backslashes last would escape
# the ones just added.
exec_value() {
    case "$1" in
        *[!A-Za-z0-9/._-]*)
            escaped="${1//\\/\\\\}"
            escaped="${escaped//\"/\\\"}"
            escaped="${escaped//\`/\\\`}"
            escaped="${escaped//\$/\\\$}"
            printf '"%s"' "$escaped"
            ;;
        *) printf '%s' "$1" ;;
    esac
}

exec_line="Exec=$(exec_value "$bin/firmauy-desktop")"
while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
        Exec=*) printf '%s\n' "$exec_line" ;;
        *)      printf '%s\n' "$line" ;;
    esac
done < "$here/$APP_ID.desktop" > "$share/applications/$APP_ID.desktop"
chmod 644 "$share/applications/$APP_ID.desktop"

install -d "$share/metainfo"
install -m 644 "$here/$APP_ID.metainfo.xml" "$share/metainfo/$APP_ID.metainfo.xml"

# Best effort: the caches make the entry and the icon appear without logging out, and every
# desktop rebuilds them on its own eventually. A machine without the tools is not a failed install.
# Best effort, and quiet about it: both complain when there is nothing to update, which on an
# uninstall is the ordinary case and reads like something went wrong.
command -v update-desktop-database >/dev/null 2>&1 &&
    update-desktop-database "$share/applications" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 &&
    gtk-update-icon-cache -qtf "$share/icons/hicolor" >/dev/null 2>&1 || true

echo "instalado en $opt"
echo "lanzador:    $bin/firmauy-desktop"
case ":$PATH:" in
    *":$bin:"*) ;;
    *) echo "aviso: $bin no está en tu PATH, así que escribir 'firmauy-desktop' en una terminal"
       echo "       no lo va a encontrar. Desde el menú de aplicaciones sí anda: la entrada"
       echo "       instalada lleva la ruta completa." ;;
esac
