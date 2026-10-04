# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the window: the router, the card lock, and the geometry it remembers."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QCloseEvent

from conftest import widget_text
from firmauy_desktop import backend, main_window, settings
from firmauy_desktop.main_window import MainWindow
from firmauy_desktop.tasks import TaskRunner
from firmauy_desktop.views import verify_view

# The minimum a stored geometry has to have been saved under to be read at all.
_MINIMUM = "{}x{}".format(*main_window._MINIMUM_SIZE)


def _window(make_view) -> MainWindow:
    return make_view(MainWindow)


def test_every_screen_is_there(make_view, qtbot):
    """Avanzado is built and added like the rest, and hidden afterwards, so the headless startup
    check still covers it. Its visibility is tested in test_advanced_view.

    Asked through the window's own API rather than the tab widget's, so the widget presenting
    the screens can change without a single test changing with it.
    """
    window = _window(make_view)
    assert window.screen_labels() == [
        "Firmar", "Verificar", "Mi cédula", "Diagnóstico", "Avanzado",
    ]
    assert window.visible_screens() == ["sign", "verify", "identity", "doctor"]


def test_verify_requested_switches_screen_and_loads_the_file(make_view, qtbot, fake_backend):
    """The one thing a screen wants from another: check what I just signed."""
    fake_backend.patch(verify_view, "verify_file", backend.VerifyResult("VALID", []))

    window = _window(make_view)
    window.go_to("sign")
    assert window.current_screen() == "sign"

    with qtbot.waitSignal(window._verify._runner.finished, timeout=5000):
        window._sign.verify_requested.emit("/tmp/doc.pdf.p7s")

    assert window.current_screen() == "verify"
    assert fake_backend.kwargs_for("verify_file") is not None


def test_go_to_ignores_a_name_that_is_not_a_screen(make_view, qtbot):
    window = _window(make_view)
    before = window.current_screen()
    window.go_to("no existe")
    assert window.current_screen() == before


# --- the card lock ----------------------------------------------------------

def test_the_card_touching_screens_share_one_lock(make_view, qtbot):
    """firmauy cannot read the card while a signing session is open on it, so this has to be a
    single lock rather than one per screen."""
    window = _window(make_view)
    assert window._sign._card is window._card
    assert window._identity._card is window._card
    assert window._doctor._card is window._card


def test_reading_the_card_is_refused_while_a_signature_is_in_flight(make_view, qtbot,
                                                                    fake_backend):
    window = _window(make_view)
    window._card.acquire("firmando")

    fake_backend.patch(
        __import__("firmauy_desktop.views.identity_view", fromlist=["x"]),
        "read_identity", backend.IdentityResult(True))
    window._identity._on_read()

    assert window._identity._runner.busy is False        # the card was never touched
    assert "ocupada" in widget_text(window._identity._status)
    assert "firmando" in widget_text(window._identity._status)


def test_a_busy_card_disables_the_other_triggers(make_view, qtbot):
    window = _window(make_view)
    window._sign.load("/tmp/doc.pdf")
    assert window._sign._button.isEnabled() is True

    window._card.acquire("leyendo la cédula")
    assert window._sign._button.isEnabled() is False
    assert window._doctor._button.isEnabled() is False

    window._card.release("leyendo la cédula")
    assert window._sign._button.isEnabled() is True
    assert window._doctor._button.isEnabled() is True


def test_a_view_built_on_its_own_still_works(make_view, qtbot):
    """The lock is optional, so a screen can be constructed alone, in a test or a tool."""
    from firmauy_desktop.views.identity_view import IdentityView

    view = make_view(IdentityView)
    assert view._card.acquire("leyendo la cédula") is True


# --- geometry ---------------------------------------------------------------

def test_the_window_remembers_its_size(make_view, qtbot):
    window = _window(make_view)
    # Comfortably inside the offscreen platform's virtual screen: Qt clamps a restored geometry
    # to the display, so a larger size would come back smaller and prove nothing.
    window.resize(640, 560)
    window._save_geometry()

    stored = settings.load().window_geometry
    assert stored                                        # base64, not a raw QByteArray
    assert isinstance(stored, str)

    reopened = _window(make_view)
    assert reopened.size() == window.size()


def test_a_first_run_gets_a_sensible_default(make_view, qtbot):
    window = _window(make_view)
    assert window.width() >= 480 and window.height() >= 520


@pytest.mark.parametrize("corrupt", ["no-es-base64-valido!!!", "ñ"])
def test_a_corrupt_stored_geometry_falls_back(make_view, qtbot, corrupt):
    """Rather than starting with a zero-sized or off-screen window, or not starting at all.

    Saved under the current minimum, or the geometry is skipped before it is read and this proves
    nothing: that is how it went on passing while a geometry that was not ASCII stopped the
    window from opening."""
    current = settings.load()
    current.window_geometry = corrupt
    current.window_geometry_min = _MINIMUM
    settings.save(current)

    window = _window(make_view)
    assert (window.width(), window.height()) == (900, 700)      # the default


# What a hand edit, or a disk going bad, can leave in any field. Strings, because that is how the
# INI backend hands every value back.
_HAND_EDITS = ["inf", "-1", "1e300", "nan", "ñ", "", "sí"]


@pytest.mark.parametrize("raw", _HAND_EDITS)
def test_no_hand_edit_keeps_the_window_or_ajustes_from_opening(make_view, raw):
    """Every field at once, all holding the same value nobody would choose, with the geometry's
    minimum set to match so the geometry is really read. The app writes none of these, and when
    something else does the answer is the defaults: "inf" in the margin stopped the app inside
    load(), a margin past a C int stopped Ajustes, and a geometry that was not ASCII stopped the
    window."""
    from dataclasses import fields

    from PySide6.QtCore import QSettings

    from firmauy_desktop.views.settings_dialog import SettingsDialog

    store = QSettings()
    for field in fields(settings.Settings):
        store.setValue(field.name, raw)
    store.setValue("window_geometry_min", _MINIMUM)
    store.sync()

    window = _window(make_view)
    SettingsDialog(settings.load(), window)

    loaded = settings.load()
    assert 0 <= loaded.stamp_margin <= settings.STAMP_MARGIN_MAX
    assert 0.0 <= loaded.stamp_image_opacity <= 1.0


# --- the menu ---------------------------------------------------------------

def test_the_menu_reaches_everything_a_keyboard_user_needs(make_view, qtbot):
    window = _window(make_view)
    labels = {
        action.text()
        for menu in window.menuBar().findChildren(type(window.menuBar().addMenu("tmp")))
        for action in menu.actions()
    }
    assert "&Ajustes..." in labels
    assert "&Acerca de" in labels
    assert "&Firmar un archivo..." in labels
    assert "&Verificar un archivo..." in labels


def test_current_screen_is_always_one_you_can_reach(make_view, qtbot):
    """Turning the advanced mode off while standing on Avanzado must not leave a person on a
    screen with no way back to it.

    QTabWidget.setTabVisible moves off a hidden tab by itself, so this passes for free today. It
    is written now because the widget presenting the screens is going to change, and nothing
    else would notice the day it stops doing that for us.
    """
    window = _window(make_view)
    window.set_advanced_mode(True)
    window.go_to("advanced")
    assert window.current_screen() == "advanced"

    window.set_advanced_mode(False)

    assert window.current_screen() in window.visible_screens()


def test_the_screen_order_is_stated_once(make_view, qtbot):
    """screen_labels and visible_screens agree on the order, so a person reading the labels and
    code reading the keys never disagree about which screen is which."""
    window = _window(make_view)
    window.set_advanced_mode(True)

    assert len(window.screen_labels()) == len(window.visible_screens())


def test_the_screens_have_keyboard_shortcuts(make_view, qtbot):
    """Compensation for what a tab bar gave away for free.

    QTabWidget came with Ctrl+Tab and the arrow keys. A list and a stack do not, and a keyboard
    regression introduced by a change nobody asked for is only noticed by the people who depend
    on it.
    """
    from PySide6.QtGui import QKeySequence, QShortcut

    window = _window(make_view)
    window.set_advanced_mode(True)
    keys = {s.key().toString(): s for s in window.findChildren(QShortcut)}

    assert [f"Ctrl+{n}" for n in range(1, 6)] == sorted(keys)

    keys[QKeySequence("Ctrl+3").toString()].activated.emit()
    assert window.current_screen() == "identity"


def test_a_shortcut_to_a_hidden_screen_goes_nowhere(make_view, qtbot):
    """Ctrl+5 with the advanced mode off would otherwise put somebody on a screen the sidebar
    does not list, with nothing selected to show them where they are."""
    from PySide6.QtGui import QKeySequence, QShortcut

    window = _window(make_view)
    window.set_advanced_mode(False)
    keys = {s.key().toString(): s for s in window.findChildren(QShortcut)}
    before = window.current_screen()

    keys[QKeySequence("Ctrl+5").toString()].activated.emit()

    assert window.current_screen() == before


def test_the_sidebar_names_the_program_in_full(qapp, make_view):
    """It read "FirmaUY", which is the library this is built on and not the name of this program.
    The room was being kept for a 24 point icon that no artwork survives.
    """
    from PySide6.QtWidgets import QLabel

    window = make_view(MainWindow)
    headings = [lbl.text() for lbl in window.findChildren(QLabel)
                if lbl.property("role") == "subtitle"]

    assert "FirmaUY Desktop" in headings
    assert window.windowTitle().endswith("FirmaUY Desktop")   # the program keeps its name


def test_the_window_title_says_where_you_are(make_view, qtbot):
    """Five windows all called "FirmaUY Desktop" cannot be told apart in a task bar, and a
    screen reader announces the window before the screen. The screen goes first; the program
    keeps its name."""
    window = _window(make_view)
    assert window.windowTitle() == "Firmar · FirmaUY Desktop"

    window.go_to("verify")

    assert window.windowTitle() == "Verificar · FirmaUY Desktop"


def test_the_window_says_it_is_not_official(qapp, make_view):
    """The banner, the README and Acerca de already say it, but the person who was handed the
    app reads none of those: the window itself is the only surface they ever see. Muted on
    purpose: it is identity, not a warning, and a warning tone would spend the colours that
    the verdicts mean something by."""
    from PySide6.QtWidgets import QLabel

    window = make_view(MainWindow)
    notes = [lbl for lbl in window.findChildren(QLabel)
             if "No es una aplicación del Estado" in lbl.text()]

    assert len(notes) == 1, "el descargo aparece una vez, en la ventana"
    assert "AGESIC" in notes[0].text()
    assert notes[0].property("tone") == "muted"


def test_a_geometry_saved_under_a_different_minimum_is_not_restored(qapp, make_view, monkeypatch):
    """Qt clamps a restored size up to the current minimum, so a window saved when it could be
    smaller reopens at a size nobody chose, in a corner from a layout that no longer exists. The
    sidebar caused exactly that: it raised the minimum from 480x520 to 720x560, and every window
    saved before it started opening at 720x560 pinned to the top left.
    """
    from firmauy_desktop import settings

    stale = settings.Settings(
        # A real blob, saved when the window could be 476x526. Kept verbatim rather than built,
        # because Qt's geometry format is private and a hand-made one would prove nothing.
        window_geometry="AdnQywADAAAAAAAAAAAAAAAAAdsAAAINAAAAAAAAAAAAAAHbAAACDQAAAAAA"
                        "AAAAB4AAAAAAAAAAAAAAAdsAAAIN",
        window_geometry_min="480x520",
    )
    monkeypatch.setattr(settings, "load", lambda: stale)

    window = make_view(MainWindow)

    assert window.size() != window.minimumSize(), "the stale geometry was restored and clamped"
    assert (window.width(), window.height()) == (900, 700)      # the default, deliberately

    # And a geometry saved under today's minimum is still offered to Qt. The decision is what is
    # asserted, not the resulting size: the offscreen platform this suite runs on refuses every
    # restoreGeometry, so the window would land on the default either way and the test would pass
    # for the wrong reason.
    fresh = settings.Settings(window_geometry=stale.window_geometry,
                              window_geometry_min=f"{window.minimumWidth()}x"
                                                  f"{window.minimumHeight()}")
    monkeypatch.setattr(settings, "load", lambda: fresh)
    tried = []
    monkeypatch.setattr(MainWindow, "restoreGeometry",
                        lambda self, blob: tried.append(bytes(blob)) or False)
    make_view(MainWindow)

    assert tried, "a geometry saved under the current minimum was never even tried"


def test_closing_spends_one_budget_for_the_whole_window(make_view, qtbot, monkeypatch):
    """Eight runners across five screens, and the budget belongs to the close, not to a screen.

    Measured before this was shared, with one parked thread in each of the eight and the shipped
    five seconds: forty seconds to close an app showing nothing. The number tracked how many
    runners there happened to be, which is the wrong thing for it to depend on.
    """
    import os
    import threading
    import time

    from firmauy_desktop import main_window as mw
    from firmauy_desktop.tasks import Task

    monkeypatch.setattr(mw, "_SIGN_BUDGET_MS", 100)          # its own, and tested below
    monkeypatch.setattr(mw, "_CLOSE_BUDGET_MS", 400)
    monkeypatch.setattr(os, "_exit", lambda code: None)      # the test wants to survive it

    release = threading.Event()
    window = _window(make_view)
    parked = []
    for view in window._screens.values():
        for value in vars(view).values():
            if isinstance(value, TaskRunner):
                task = Task(lambda: release.wait(30))
                value._retired.append(task)
                task.start()
                parked.append(task)

    assert len(parked) >= 5, "one runner per screen at least, or this proves nothing"
    qtbot.wait(50)

    start = time.monotonic()
    window.closeEvent(QCloseEvent())
    spent = (time.monotonic() - start) * 1000

    # Firmar's own budget plus the one the other four share, with room for a loaded runner. Seven
    # runners each taking 400 ms would be 2900, which is what this has to be able to tell apart.
    assert spent < 100 + 400 * 2, f"gastó {spent:.0f} ms, o sea un presupuesto por runner"

    release.set()
    for task in parked:
        task.wait(5000)


def test_closing_over_a_thread_that_will_not_stop_leaves_on_purpose(make_view, qtbot, monkeypatch):
    """The two things this waits on cannot be interrupted: a blocked card read and a revocation
    lookup that is not answering. Qt aborts the process when such a thread is destroyed.

    Measured on the way in: exit 134, with "QThread: Destroyed while thread is still running" as
    the last thing an app for signing documents says. So the exit is taken deliberately instead,
    and noted first, because a record that stops mid-sentence does not say why.
    """
    import os
    import threading

    from firmauy_desktop import activity
    from firmauy_desktop import main_window as mw
    from firmauy_desktop.tasks import Task

    monkeypatch.setattr(mw, "_SIGN_BUDGET_MS", 200)
    monkeypatch.setattr(mw, "_CLOSE_BUDGET_MS", 200)
    codes = []
    monkeypatch.setattr(os, "_exit", codes.append)

    activity.configure(True)
    release = threading.Event()
    window = _window(make_view)
    task = Task(lambda: release.wait(30))
    window._screens["sign"]._runner._retired.append(task)
    task.start()
    qtbot.wait(50)

    window.closeEvent(QCloseEvent())

    assert codes == [0], "no salió, o salió con un código que dice que algo falló"
    assert "cierre forzado" in activity.log_path().read_text(encoding="utf-8")

    release.set()
    task.wait(5000)


def test_closing_with_nothing_in_flight_does_not_force_anything(make_view, qtbot, monkeypatch):
    """The ordinary close, which is every close. Leaving by the front door has to stay the
    default, or the app would exit hard every single time and nobody would notice until Qt had
    something it needed to do on the way out."""
    import os

    codes = []
    monkeypatch.setattr(os, "_exit", codes.append)

    window = _window(make_view)
    window.closeEvent(QCloseEvent())

    assert codes == []


def test_a_signature_in_flight_gets_first_claim_on_the_close_budget(make_view, qtbot, monkeypatch):
    """One shared budget is less total waiting than a budget each, so the order matters now.

    Firmar is the only screen whose work writes a document somebody asked for. Reading the budget
    in whatever order the screens happen to be stored would leave a signature in flight with
    whatever four other screens had not spent, which is the one case worth protecting.
    """
    import os
    import threading

    from firmauy_desktop import main_window as mw
    from firmauy_desktop.tasks import Task

    monkeypatch.setattr(mw, "_SIGN_BUDGET_MS", 100)
    monkeypatch.setattr(mw, "_CLOSE_BUDGET_MS", 600)
    monkeypatch.setattr(os, "_exit", lambda code: None)

    release = threading.Event()
    window = _window(make_view)

    served = []
    for key, view in window._screens.items():
        original = view.shutdown

        def record(budget, key=key, original=original):
            served.append(key)
            return original(budget)

        monkeypatch.setattr(view, "shutdown", record)

    task = Task(lambda: release.wait(30))
    window._screens["verify"]._runner._retired.append(task)
    task.start()
    qtbot.wait(50)

    window.closeEvent(QCloseEvent())

    assert served[0] == "sign"
    assert sorted(served) == sorted(window._screens)      # and nobody is skipped

    release.set()
    task.wait(5000)


def test_firmar_waits_longer_than_the_screens_whose_work_is_cheap_to_repeat(make_view, qtbot,
                                                                            monkeypatch):
    """Two budgets, because the screens are not worth the same on the way out.

    Nothing the exit interrupts can be corrupted, which was measured: a signed document is staged
    beside the target and moved with os.replace, so a kill mid-write leaves the old file whole,
    and the CA cache is revalidated against pinned fingerprints on load. What a kill costs is the
    work. Reading the cédula again is a click. A signature is the PIN over again, and five seconds
    is not much for a large PDF plus a round trip to a timestamping authority.

    Asserted on the object each screen is handed, not on a stopwatch, so it says what it means:
    Firmar is given a budget of its own and the other four are given one and the same.
    """
    from firmauy_desktop import main_window as mw
    from firmauy_desktop.tasks import Deadline

    window = _window(make_view)
    given = {}
    for key, view in window._screens.items():
        original = view.shutdown

        def record(budget, key=key, original=original):
            given[key] = budget
            return original(budget)

        monkeypatch.setattr(view, "shutdown", record)

    window.closeEvent(QCloseEvent())

    assert given["sign"] == mw._SIGN_BUDGET_MS
    assert mw._SIGN_BUDGET_MS > mw._CLOSE_BUDGET_MS

    rest = [budget for key, budget in given.items() if key != "sign"]
    assert len(rest) == 4
    assert all(isinstance(budget, Deadline) for budget in rest)
    assert len({id(budget) for budget in rest}) == 1, "cada una recibió su propio presupuesto"
