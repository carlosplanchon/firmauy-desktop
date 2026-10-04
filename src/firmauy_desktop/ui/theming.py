# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Turning the tokens into an application that looks like something.

Named ``theming`` so the module and the ``theme`` singleton it exports do not share one name.

Style sheets are the primary mechanism, not QPalette. Qt's own documentation is direct about it:
style sheets "guarantee that customizations are consistently applied across different styles and
platforms, unlike palette manipulations which may be overridden by native theme engines", and
``QApplication.setPalette`` carries an explicit "avoid using with Qt Style Sheets". The palette
here covers only the handful of roles a stylesheet cannot reach.
"""

from __future__ import annotations

from pathlib import Path
from string import Template

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFontInfo, QGuiApplication, QPalette

from firmauy_desktop.ui import tokens

QSS_PATH = Path(__file__).resolve().parent.parent / "assets" / "app.qss"

# Same idiom as app.py uses for the window icon, and documented there: one path that resolves
# identically from a source checkout, an installed wheel and a PyInstaller bundle.


def system_scheme() -> str:
    """What the desktop is set to. Unknown, which is what the offscreen platform reports, is
    treated as light: that is also the branch the whole test suite exercises."""
    hints = QGuiApplication.styleHints()
    return "dark" if hints and hints.colorScheme() == Qt.ColorScheme.Dark else "light"


def base_point_size(app) -> float:
    """The platform's own default font size, which the type scale is relative to.

    pointSizeF comes back -1 when a font was specified in pixels, which happens on some Linux
    setups, and QFontInfo is what resolves it to what is actually being drawn.
    """
    size = app.font().pointSizeF()
    if size <= 0:
        size = QFontInfo(app.font()).pointSizeF()
    return size if size > 0 else 10.0


class Theme(QObject):
    """The active look. One application, one scheme, so one instance.

    Anything hand-painted (a tinted icon, a QPainter) listens to ``changed``. Everything driven
    by the stylesheet fixes itself for free, because re-applying it re-polishes every widget.
    """

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._app = None
        self._preference = "system"
        self._scheme = "light"
        self._base_pt = 10.0

    # --- applying -----------------------------------------------------------

    def apply(self, app, preference: str = "system") -> None:
        """Install the palette and the stylesheet, in that order.

        The order matters and the attribute below matters more: a style sheet otherwise disables
        regular palette and font propagation to child widgets.
        """
        self._app = app
        app.setAttribute(Qt.ApplicationAttribute.AA_UseStyleSheetPropagationInWidgetStyles, True)
        self._base_pt = base_point_size(app)
        hints = QGuiApplication.styleHints()
        if hints is not None:
            hints.colorSchemeChanged.connect(self._on_system_scheme_changed)
        self.set_preference(preference)

    def _repaint(self) -> None:
        if self._app is None:
            return
        self._app.setPalette(self.build_palette())
        self._app.setStyleSheet(self.build_qss())

    def _on_system_scheme_changed(self, _scheme) -> None:
        """Somebody's desktop went dark at sunset. Only matters while following the system."""
        if self._preference == "system":
            self.set_preference("system")

    # --- what is active -----------------------------------------------------

    def scheme(self) -> str:
        """The scheme actually in force, "light" or "dark"."""
        return self._scheme

    def preference(self) -> str:
        """What was asked for: "system", "light" or "dark"."""
        return self._preference

    def set_preference(self, preference: str) -> None:
        if preference not in ("system", "light", "dark"):
            preference = "system"
        self._preference = preference

        hints = QGuiApplication.styleHints()
        if hints is not None:
            # Told to Qt as well, not just to our own stylesheet, so QFileDialog, QMessageBox and
            # the window frame follow rather than staying light inside a dark app.
            if preference == "system":
                hints.unsetColorScheme()
            else:
                hints.setColorScheme(
                    Qt.ColorScheme.Dark if preference == "dark" else Qt.ColorScheme.Light)

        scheme = system_scheme() if preference == "system" else preference
        changed = scheme != self._scheme
        self._scheme = scheme
        self._repaint()
        if changed or self._app is not None:
            self.changed.emit()

    # --- lookups ------------------------------------------------------------

    def hex(self, token: str) -> str:
        palette = tokens.palette_for(self._scheme)
        if token not in palette:
            raise KeyError(f"unknown colour token: {token}")
        return palette[token]

    def color(self, token: str) -> QColor:
        """For the cases where a colour is a value: tinting an icon, painting by hand."""
        return QColor(self.hex(token))

    def space(self, name: str) -> int:
        return tokens.SPACE[name]

    def base_pt(self) -> float:
        return self._base_pt

    # --- building -----------------------------------------------------------

    def build_qss(self) -> str:
        """Substitute the tokens into the stylesheet template.

        `string.Template` rather than str.format, because QSS is made of braces. `substitute`
        rather than `safe_substitute`, because a typo should stop the app at startup instead of
        rendering as a rule Qt drops without a word.
        """
        template = Template(QSS_PATH.read_text(encoding="utf-8"))
        return template.substitute(tokens.qss_variables(self._scheme, self._base_pt))

    def build_palette(self) -> QPalette:
        """Only the roles a stylesheet cannot reach.

        Text selection and placeholder text have no QSS selector at all, and the window/base/text
        trio is the coherent fallback for anything the stylesheet does not name.
        """
        palette = QPalette()
        colour = self.color
        palette.setColor(QPalette.ColorRole.Window, colour("bg.app"))
        palette.setColor(QPalette.ColorRole.WindowText, colour("fg.default"))
        palette.setColor(QPalette.ColorRole.Base, colour("bg.surface"))
        palette.setColor(QPalette.ColorRole.AlternateBase, colour("bg.hover"))
        palette.setColor(QPalette.ColorRole.Text, colour("fg.default"))
        palette.setColor(QPalette.ColorRole.PlaceholderText, colour("fg.faint"))
        palette.setColor(QPalette.ColorRole.Button, colour("bg.surface"))
        palette.setColor(QPalette.ColorRole.ButtonText, colour("fg.default"))
        palette.setColor(QPalette.ColorRole.Highlight, colour("accent.default"))
        palette.setColor(QPalette.ColorRole.HighlightedText, colour("fg.on-accent"))
        palette.setColor(QPalette.ColorRole.Link, colour("accent.default"))
        palette.setColor(QPalette.ColorRole.ToolTipBase, colour("bg.surface"))
        palette.setColor(QPalette.ColorRole.ToolTipText, colour("fg.default"))
        disabled = QPalette.ColorGroup.Disabled
        palette.setColor(disabled, QPalette.ColorRole.WindowText, colour("fg.faint"))
        palette.setColor(disabled, QPalette.ColorRole.Text, colour("fg.faint"))
        palette.setColor(disabled, QPalette.ColorRole.ButtonText, colour("fg.faint"))
        return palette


theme = Theme()
