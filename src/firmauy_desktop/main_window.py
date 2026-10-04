# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""The window: the screens, the menu, and the little wiring that has to live above them.

The views know nothing about each other. When one wants something to happen elsewhere it says
so with a signal, and this is the only place that decides what that means. It is also the only
holder of the card lock, which is what keeps two screens from reaching for the reader at once.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from firmauy_desktop import activity, settings
from firmauy_desktop.dialogs import about_dialog
from firmauy_desktop.tasks import CardLock, Deadline
from firmauy_desktop.ui import components as c
from firmauy_desktop.ui import icons, tokens
from firmauy_desktop.ui.theming import theme
from firmauy_desktop.views.advanced_view import AdvancedView
from firmauy_desktop.views.doctor_view import DoctorView
from firmauy_desktop.views.identity_view import IdentityView
from firmauy_desktop.views.settings_dialog import open_settings
from firmauy_desktop.views.sign_view import SignView
from firmauy_desktop.views.verify_view import VerifyView

_DEFAULT_SIZE = (900, 700)
# Wider than it was: a 200 point sidebar has to come off the reading area, not out of it. The
# geometry tests ask for at least the old numbers, so a larger minimum satisfies them.
_MINIMUM_SIZE = (720, 560)
_SIDEBAR_WIDTH = 200

# How long closing the window waits for work that cannot be interrupted. Two budgets, because the
# screens are not worth the same on the way out.
#
# Firmar gets its own and a long one. Nothing it writes can be corrupted by the exit below, but a
# signature that does not finish is thrown away with the PIN that paid for it, and five seconds is
# not much for a large PDF plus a round trip to a timestamping authority. It is bounded rather than
# unbounded because firmauy and the TSA have timeouts of their own, so a signature takes long, it
# does not hang forever.
_SIGN_BUDGET_MS = 30_000

# Everything else shares this one: reading the cédula, verifying, the reader list, the CA refresh.
# Losing any of those costs a click to run again, so the number that matters is how long somebody
# who pressed the X waits before deciding the app has hung.
_CLOSE_BUDGET_MS = 5000

# The screens, in the order a person meets them, with the icon each one is known by. One list, so
# the order is not spread between the construction, the labels and whatever widget presents them.
_SCREENS = (
    ("sign", "Firmar", "pen"),
    ("verify", "Verificar", "shield-check"),
    ("identity", "Mi cédula", "id-card"),
    ("doctor", "Diagnóstico", "activity"),
    ("advanced", "Avanzado", "sliders"),
)


def _row_of(key: str) -> int:
    """Where a screen sits in the nav. One list decides the order, so this is the only lookup."""
    return next(row for row, (k, _label, _icon) in enumerate(_SCREENS) if k == key)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FirmaUY Desktop")
        self.setMinimumSize(*_MINIMUM_SIZE)

        # One lock for the whole window. Views that talk to the card take it, so reading the
        # cédula while a signature is in flight is refused by the app rather than by pcscd.
        self._card = CardLock(self)

        self._sign = SignView(self._card)
        self._verify = VerifyView()
        self._identity = IdentityView(self._card)
        self._doctor = DoctorView(self._card)
        self._advanced = AdvancedView(self._card)
        self._screens = {
            "sign": self._sign,
            "verify": self._verify,
            "identity": self._identity,
            "doctor": self._doctor,
            "advanced": self._advanced,
        }

        self._stack = QStackedWidget()
        for key, _label, _icon in _SCREENS:
            self._stack.addWidget(self._screens[key])

        central = QWidget()
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._build_sidebar())
        row.addWidget(self._stack, stretch=1)
        column.addLayout(row, stretch=1)
        column.addWidget(self._build_disclaimer())
        self.setCentralWidget(central)

        # "Verify what I just signed", which is the one thing a screen wants from another.
        self._sign.verify_requested.connect(self._on_verify_requested)

        self._build_menu()
        self._build_shortcuts()
        # Avanzado is built and added to the stack unconditionally and only then hidden from the
        # sidebar: building it conditionally would leave the screen out of the headless startup
        # check, which is the only thing that catches a view that fails to build at all.
        self.set_advanced_mode(settings.load().advanced_mode)
        self._restore_geometry()

    # --- navigation ---------------------------------------------------------
    #
    # These four say what a person can see and where they are, in the app's own words. They were
    # written while this was still a QTabWidget, precisely so that swapping it for a list and a
    # stack would touch this file and nothing in tests/. That is what happened.

    def go_to(self, key: str) -> None:
        """Show a screen. Silently ignores one a person cannot currently reach."""
        if key not in self.visible_screens():
            return
        self._stack.setCurrentWidget(self._screens[key])
        self._nav.setCurrentRow(_row_of(key))

    def screen_labels(self) -> list[str]:
        """Every screen's label, in the order a person meets them, visible or not."""
        return [label for _key, label, _icon in _SCREENS]

    def visible_screens(self) -> list[str]:
        """The keys a person can reach right now. Avanzado is missing unless it is turned on."""
        return [key for row, (key, _label, _icon) in enumerate(_SCREENS)
                if not self._nav.isRowHidden(row)]

    def current_screen(self) -> str:
        """The key of the screen being shown, or "" if it is somehow none of them."""
        current = self._stack.currentWidget()
        return next((key for key, view in self._screens.items() if view is current), "")

    # --- the sidebar --------------------------------------------------------

    def _build_sidebar(self) -> QWidget:
        """The app's mark, the five screens, and Ajustes at the bottom.

        A list rather than a tab bar: five destinations with icons and Spanish labels do not fit
        across the top of a 720 point window, and a tab bar reads as "views of one thing" where
        these are five separate errands.
        """
        bar = QWidget()
        bar.setObjectName("sidebar")
        bar.setFixedWidth(_SIDEBAR_WIDTH)
        column = QVBoxLayout(bar)
        column.setContentsMargins(*(tokens.SPACE["md"],) * 4)
        column.setSpacing(tokens.SPACE["md"])

        column.addLayout(self._build_brand())

        self._nav = QListWidget()
        self._nav.setObjectName("nav")
        self._nav.setAccessibleName("Pantallas")
        self._nav.setIconSize(QSize(tokens.ICON["nav"], tokens.ICON["nav"]))
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for _key, label, _icon in _SCREENS:
            self._nav.addItem(QListWidgetItem(label))
        column.addWidget(self._nav)

        column.addStretch()

        self._settings_btn = QPushButton("Ajustes")
        self._settings_btn.setToolTip("Cómo firma la app y qué apariencia usa (Ctrl+,).")
        self._settings_btn.setObjectName("navAction")
        self._settings_btn.setIconSize(QSize(tokens.ICON["nav"], tokens.ICON["nav"]))
        self._settings_btn.clicked.connect(self.open_settings)
        column.addWidget(self._settings_btn)

        # Connected last, and only once everything it touches exists: setCurrentRow fires
        # currentRowChanged synchronously, which would otherwise repaint icons onto a button
        # that has not been built yet.
        self._nav.currentRowChanged.connect(self._on_nav_changed)
        self._nav.setCurrentRow(0)
        self._paint_nav_icons()
        # The tints are baked into pixmaps, so a scheme change repaints them rather than
        # restyling them.
        theme.changed.connect(self._paint_nav_icons)
        return bar

    def _build_brand(self) -> QHBoxLayout:
        """The sidebar's heading: the program's full name, and nothing beside it.

        No icon beside it, and no shortened name to make room for one. Measured, no artwork
        survives 24 points: an icon there reduces to a smudge, and so does the project's logo,
        and a heading that has to be squinted at adds nothing a heading is for. The icon still
        identifies the app where it is seen big enough to tell apart, on the window and on the
        task bar.
        """
        head = QHBoxLayout()
        head.addWidget(c.label("FirmaUY Desktop", role="subtitle", wrap=False))
        head.addStretch()
        return head

    def _build_disclaimer(self) -> QWidget:
        """One quiet line across the foot of the window, saying who this program is not.

        The banner, the README and Acerca de already say it, but the person who was handed the
        app reads none of those: the window is the only surface they ever see, and the moment
        they trust it most is with the PIN dialog open in front of it. It reads as identity,
        not as a warning, in the same muted small print as every other explanation. And it
        stays out of the PIN dialog on purpose: a person should learn to look at who is asking
        for the PIN, not to accept PIN dialogs that come with fine print.
        """
        bar = QWidget()
        bar.setObjectName("disclaimer")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(tokens.SPACE["md"], tokens.SPACE["xs"],
                               tokens.SPACE["md"], tokens.SPACE["xs"])
        note = c.Note("Proyecto comunitario independiente. "
                      "No es una aplicación del Estado ni de AGESIC.")
        note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        note.setToolTip("Lo que no es oficial es el programa, no la firma: la firma la hace "
                        "tu cédula con su certificado del Ministerio del Interior, y vale lo "
                        "mismo sin importar qué programa la produzca.")
        lay.addWidget(note)
        return bar

    def _on_nav_changed(self, row: int) -> None:
        if 0 <= row < len(_SCREENS):
            self._stack.setCurrentWidget(self._screens[_SCREENS[row][0]])
            # The task bar and a screen reader get "Verificar", not five windows all called
            # the same thing. The screen first, and the program keeps its name.
            self.setWindowTitle(f"{_SCREENS[row][1]} · FirmaUY Desktop")
        self._paint_nav_icons()

    def _paint_nav_icons(self) -> None:
        """Tint each icon for where it stands: the current screen in the accent, the rest muted.

        Not something the stylesheet can reach. A QSS rule styles an item's text and background,
        but the icon is a pixmap whose colour was decided when it was painted.
        """
        current = self._nav.currentRow()
        for row, (_key, _label, name) in enumerate(_SCREENS):
            tone = "accent.default" if row == current else "fg.muted"
            self._nav.item(row).setIcon(icons.icon(name, tone, tokens.ICON["nav"]))
        self._settings_btn.setIcon(icons.icon("gear", "fg.muted", tokens.ICON["nav"]))

    def _build_shortcuts(self) -> None:
        """Ctrl+1 to Ctrl+5, which is what a tab bar gave away for free.

        QTabWidget came with Ctrl+Tab and the arrow keys built in. A list and a stack do not, and
        losing keyboard navigation to a change nobody asked for is the kind of regression that
        only gets noticed by the people who rely on it.
        """
        for row, (key, _label, _icon) in enumerate(_SCREENS, start=0):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{row + 1}"), self)
            shortcut.activated.connect(lambda k=key: self.go_to(k))

    def open_settings(self) -> None:
        """Each screen reads the settings when it starts work, so nothing needs telling.

        Except this one: whether Avanzado is listed is a window decision, not a screen one, so
        the window is what has to act on it.
        """
        saved = open_settings(self)
        if saved is not None:
            self.set_advanced_mode(saved.advanced_mode)
            # Same reason: nothing reads this per operation, so somebody has to act on it.
            activity.configure(saved.activity_log)

    def set_advanced_mode(self, on: bool) -> None:
        """Show or hide the PKCS#11 introspection screen, and remember the choice."""
        self._nav.setRowHidden(_row_of("advanced"), not on)
        # QTabWidget.setTabVisible moved off a hidden tab by itself. A hidden list row does not,
        # so turning the mode off while standing on Avanzado would leave somebody on a screen
        # with no way back to it.
        if not on and self.current_screen() == "advanced":
            self.go_to("sign")
        current = settings.load()
        if current.advanced_mode != on:
            current.advanced_mode = on
            settings.save(current)

    def _on_verify_requested(self, path: str) -> None:
        self.go_to("verify")
        self._verify.load(path)

    def _build_menu(self) -> None:
        archivo = self.menuBar().addMenu("&Archivo")
        archivo.addAction("&Firmar un archivo...", self._pick_to_sign)
        archivo.addAction("&Verificar un archivo...", self._pick_to_verify)
        archivo.addSeparator()
        salir = archivo.addAction("&Salir", self.close)
        salir.setShortcut(QKeySequence.StandardKey.Quit)

        herramientas = self.menuBar().addMenu("&Herramientas")
        ajustes = herramientas.addAction("&Ajustes...", self.open_settings)
        ajustes.setShortcut(QKeySequence.StandardKey.Preferences)
        herramientas.addAction("&Diagnóstico", lambda: self.go_to("doctor"))

        ayuda = self.menuBar().addMenu("A&yuda")
        ayuda.addAction("&Acerca de", lambda: about_dialog(self))

    def _pick_to_sign(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Elegir el archivo a firmar")
        if path:
            self.go_to("sign")
            self._sign.load(path)

    def _pick_to_verify(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Elegir el archivo firmado")
        if path:
            self.go_to("verify")
            self._verify.load(path)

    # --- geometry -----------------------------------------------------------

    def _restore_geometry(self) -> None:
        """Give back the window the person left, or the default when there is no such thing.

        Qt clamps a restored size up to the current minimum, so a geometry saved when the window
        could be smaller comes back as a size nobody chose, at a position from a layout that no
        longer exists. That is what the sidebar did: it raised the minimum from 480x520 to
        720x560, and every window saved before it started opening at exactly 720x560 in the
        top-left corner. Storing the minimum alongside the geometry is what tells the two apart,
        since Qt's blob is a private format and parsing it would be worse.
        """
        stored = settings.load()
        if (stored.window_geometry
                and stored.window_geometry_min == self._geometry_min()
                and self.restoreGeometry(
                    QByteArray.fromBase64(stored.window_geometry.encode("ascii")))):
            return
        self.resize(*_DEFAULT_SIZE)

    def _geometry_min(self) -> str:
        return f"{self.minimumWidth()}x{self.minimumHeight()}"

    def _save_geometry(self) -> None:
        current = settings.load()
        current.window_geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        current.window_geometry_min = self._geometry_min()
        settings.save(current)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Wait for the card and file work still in flight before the window goes away.

        Signing a large PDF or waiting on a card that is not answering both outlive an impatient
        click on the close button, and letting Python collect a running QThread aborts the
        process.

        One budget for the whole window, not one per screen. There are eight runners across five
        screens, so a budget each was eight budgets: measured, with a parked thread in every one,
        closing took 40 seconds.

        And a thread can outlast any budget, because the two this waits on cannot be interrupted:
        a blocked card read and a revocation lookup that is not answering. Qt aborts the process
        when such a thread is destroyed, which is measured too, exit 134 with "QThread: Destroyed
        while thread is still running" on the way out. A crash on the way out of a signing app is
        worth avoiding, so the exit is taken deliberately rather than suffered.

        Nothing is corrupted by taking it, which is narrower than "nothing is lost" and is what
        was actually measured. The settings are written and synced by settings.save, which the
        line below calls before any waiting starts, and the record flushes on every line, since
        logging flushes at the end of each emit: a second process reading the same state
        directory found both intact. Neither writer can be caught half way, for two different
        reasons. A signed document is staged in a randomly named file beside the target and moved
        into place with os.replace, so killing the process mid-write leaves the old file untouched
        and an orphan .part behind: measured, target unchanged at 26 bytes with 15000 in the
        staging file. The national CA cache is not written atomically, and does not need to be,
        because firmauy re-checks both pinned fingerprints when it loads it and treats anything
        incomplete as absent, falling back to the anchors bundled in the build.

        What is lost is the work itself. A signature that had not finished is gone, PIN and all,
        and has to be made again, so Firmar is waited on first and on its own longer budget while
        the four screens whose work costs a click to repeat share the short one.
        """
        self._save_geometry()

        alive = list(self._sign.shutdown(_SIGN_BUDGET_MS))

        rest = Deadline(_CLOSE_BUDGET_MS)
        alive += [task for key, view in self._screens.items() if view is not self._sign
                  for task in view.shutdown(rest)]

        if alive:
            activity.event("cierre forzado", n=len(alive))
            os._exit(0)

        super().closeEvent(event)
