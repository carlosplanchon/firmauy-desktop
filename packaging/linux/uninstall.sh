#!/usr/bin/env bash
# Undo install.sh, and leave nothing of the application behind except what the person made.
#
# The settings and the activity record are deliberately not touched. Removing a program is not the
# same as asking for your preferences to be thrown away, and the record is the one thing somebody
# might be uninstalling in order to send. Both are named below so nobody has to go looking.
#
#     packaging/linux/uninstall.sh [--system]
set -euo pipefail

APP_ID="com.firmauy.firmauydesktop"

if [ "${1:-}" = "--system" ]; then
    # Same question as install.sh, asked before the first rm for the same reason.
    if [ "$(id -u)" -ne 0 ]; then
        echo "error: --system desinstala de toda la máquina y necesita root:" >&2
        printf '       sudo %q --system\n' "$0" >&2
        exit 1
    fi
    opt="/opt/firmauy-desktop"
    bin="/usr/local/bin"
    share="/usr/local/share"
else
    opt="$HOME/.local/opt/firmauy-desktop"
    bin="$HOME/.local/bin"
    share="${XDG_DATA_HOME:-$HOME/.local/share}"     # the same place install.sh wrote to
fi

rm -rf "$opt"
rm -f "$bin/firmauy-desktop"
rm -f "$share/applications/$APP_ID.desktop"
rm -f "$share/metainfo/$APP_ID.metainfo.xml"
rm -f "$share/icons/hicolor/scalable/apps/$APP_ID.svg"
rm -f "$share/icons/hicolor/512x512/apps/$APP_ID.png"

# Best effort, and quiet about it: both complain when there is nothing to update, which on an
# uninstall is the ordinary case and reads like something went wrong.
command -v update-desktop-database >/dev/null 2>&1 &&
    update-desktop-database "$share/applications" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 &&
    gtk-update-icon-cache -qtf "$share/icons/hicolor" >/dev/null 2>&1 || true

echo "desinstalado."
echo

# Worked out rather than written down. The app stores neither of these at a fixed path: the
# settings go through QSettings and the record through QStandardPaths, and both follow
# XDG_CONFIG_HOME and XDG_STATE_HOME when they are set. Measured with both pointed elsewhere, the
# files land there, so naming ~/.config and ~/.local/state would be telling somebody to look in
# the wrong place on the machines whose owner configured this.
if [ "${1:-}" = "--system" ]; then
    echo "Quedan, a propósito, los ajustes y el registro de actividad, que son de cada"
    echo "usuario y no de la instalación. Están en las carpetas de configuración y de"
    echo "estado de cada uno, no acá: esto se ejecutó como root y borrarlos no le"
    echo "correspondía."
else
    config="${XDG_CONFIG_HOME:-$HOME/.config}/firmauy"
    state="${XDG_STATE_HOME:-$HOME/.local/state}/firmauy"
    echo "Quedan, a propósito:"
    printf '  los ajustes            %s%s\n' "$config/" \
        "$([ -e "$config" ] || echo '   (no hay)')"
    printf '  el registro, si lo     %s%s\n' "$state/" \
        "$([ -e "$state" ] || echo '   (no hay)')"
    echo "  habías activado"
fi
