# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""What the app says to somebody who is not looking at it.

The theme running through these is WCAG 1.4.1: colour, and an icon that carries meaning without
saying it, are the same failure. The app is full of green ticks and red crosses, and the rows
they annotate mostly do not repeat the answer in their text.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from firmauy_desktop.main_window import MainWindow
from firmauy_desktop.ui import components as c
from firmauy_desktop.ui import tokens
from firmauy_desktop.views import doctor_view, identity_view
from firmauy_desktop.widgets import DropArea


# --- the icons that carry an answer -----------------------------------------

@pytest.mark.parametrize("status, spoken", [
    ("PASS", "correcto"), ("WARN", "advertencia"), ("FAIL", "falla"),
    ("VALID", "correcto"), ("INDETERMINATE", "advertencia"), ("INVALID", "falla"),
])
def test_a_status_icon_says_what_it_shows(qapp, status, spoken):
    assert c.StatusIcon(status).accessibleName() == spoken


def test_a_check_row_is_not_the_same_row_whether_it_passed_or_failed(qapp):
    """The bug this closes: the glossed name and the detail are identical for a check that
    passed and one that failed, so the icon was the only thing carrying the answer and it said
    nothing at all."""
    passed = c.CheckList()
    passed.set_checks([c.CheckItem("PASS", "pcscd running")])
    failed = c.CheckList()
    failed.set_checks([c.CheckItem("FAIL", "pcscd running")])

    def spoken(checks):
        return [lbl.accessibleName() or lbl.text()
                for lbl in checks.findChildren(QLabel)]

    assert spoken(passed) != spoken(failed)


def test_a_mark_says_yes_or_no(qapp):
    assert c.Mark(True).accessibleName() == "sí"
    assert c.Mark(False).accessibleName() == "no"
    assert c.Mark(None).accessibleName() == ""


def test_every_status_has_a_word_for_it(qapp):
    """Same shape as the icon and tone maps: a status missing here is one that goes unsaid."""
    assert set(tokens.STATUS_SPOKEN) == set(tokens.STATUS_TONE)


def test_the_two_vocabularies_say_the_same_thing(qapp):
    for good, bad in (("PASS", "VALID"), ("WARN", "INDETERMINATE"), ("FAIL", "INVALID")):
        assert tokens.STATUS_SPOKEN[good] == tokens.STATUS_SPOKEN[bad]


# --- reaching things without a mouse ----------------------------------------

def test_the_drop_area_can_be_reached_by_keyboard(qapp):
    """It was a mouse-only target: a keyboard user could press the button inside it, but the
    zone itself was never announced as the thing files go to."""
    area = DropArea("Arrastrá un archivo acá")

    assert area.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert area.accessibleName()
    assert area.accessibleDescription()


def test_the_drop_area_opens_the_picker_from_the_keyboard(qapp, monkeypatch):
    """A focus ring on a box has to mean something can be done to it."""
    from PySide6.QtGui import QKeyEvent

    opened = []
    area = DropArea("Arrastrá un archivo acá")
    monkeypatch.setattr(area, "_on_browse", lambda: opened.append(True))

    for key in (Qt.Key.Key_Space, Qt.Key.Key_Return):
        area.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))

    assert opened == [True, True]


def test_the_drop_area_does_not_leave_two_tab_stops_that_do_one_thing(qapp):
    area = DropArea("Arrastrá un archivo acá")
    assert area._browse.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_a_field_with_only_a_placeholder_still_has_a_name(qapp, make_view):
    """A placeholder disappears the moment somebody types, and is not a label."""
    view = make_view(identity_view.IdentityView)
    assert view._ci_input.accessibleName()


def test_every_screen_says_which_one_it_is(qapp, make_view):
    window = make_view(MainWindow)
    for key, view in window._screens.items():
        assert view.accessibleName(), key


def test_the_sidebar_is_named(qapp, make_view):
    window = make_view(MainWindow)
    assert window._nav.accessibleName()


# --- nothing is greyed out by disabling it ----------------------------------

def test_no_explanation_is_disabled_to_render_grey(qapp, make_view):
    """A screen reader announces a disabled widget as unavailable. Three labels in this app were
    disabled purely to come out grey, which told somebody an explanation was out of reach."""
    window = make_view(MainWindow)
    offenders = [
        lbl.text()[:50] for lbl in window.findChildren(QLabel)
        if lbl.text() and not lbl.isEnabled()
    ]
    assert offenders == []


def test_the_doctor_note_is_muted_rather_than_disabled(qapp, make_view):
    view = make_view(doctor_view.DoctorView)
    notes = [n for n in view.findChildren(c.Note) if "Ajustes decide" in n.text()]
    assert notes and notes[0].isEnabled() is True


def test_the_settings_dialog_has_no_disabled_explanation_either(qapp, qtbot):
    """It is not a child of the window, so the walk above never reaches it. Its note was the
    third and last of the three."""
    from firmauy_desktop.settings import Settings
    from firmauy_desktop.views.settings_dialog import SettingsDialog

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    offenders = [
        lbl.text()[:50] for lbl in dialog.findChildren(QLabel)
        if lbl.text() and not lbl.isEnabled()
    ]
    assert offenders == []


# --- the keyboard tour ------------------------------------------------------

def _focus_chain(qapp, window, limit: int = 60) -> list:
    """Everything Tab reaches, starting from the sidebar, in order.

    The processEvents calls are load-bearing: focus is delivered through the event loop, and
    without them focusWidget() answers None and the walk silently reports an empty chain.
    """
    window.show()
    qapp.processEvents()
    window._nav.setFocus()
    qapp.processEvents()
    seen, chain = set(), []
    for _ in range(limit):
        widget = qapp.focusWidget()
        if widget is None or id(widget) in seen:
            break
        seen.add(id(widget))
        chain.append(widget)
        window.focusNextChild()
        qapp.processEvents()
    return chain


def test_the_sidebar_comes_first(qapp, make_view):
    """Tab from the top of the window lands on navigation, not somewhere inside a screen."""
    window = make_view(MainWindow)
    assert _focus_chain(qapp, window)[0] is window._nav


@pytest.mark.parametrize("key", ["sign", "verify", "identity", "doctor", "advanced"])
def test_every_control_on_a_screen_can_be_reached_without_a_mouse(qapp, make_view, key):
    """Walked rather than reasoned about. A widget added inside a layout that nothing focuses is
    invisible to a keyboard, and looks perfectly fine in a screenshot.

    Only what is on screen and usable: a hidden Guardar or a disabled Firmar is correctly absent.
    """
    from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QPushButton

    window = make_view(MainWindow)
    window.set_advanced_mode(True)
    window.show()
    window.go_to(key)
    screen = window._screens[key]

    reachable = {id(w) for w in _focus_chain(qapp, window)}
    controls = [w for kind in (QPushButton, QLineEdit, QComboBox, QCheckBox)
                for w in screen.findChildren(kind)]
    missing = [
        f"{type(w).__name__}: {w.text() if hasattr(w, 'text') else ''}"
        for w in controls
        if w.isVisible() and w.isEnabled() and w.focusPolicy() != Qt.FocusPolicy.NoFocus
        and id(w) not in reachable
    ]
    assert missing == []


# --- every field is named ---------------------------------------------------

def _unnamed_fields(root) -> list[str]:
    """Text inputs and combos that a screen reader would announce as just their kind.

    A buddy counts, and so does an accessible name. Neither counts if the buddy points at the
    wrapper widget holding the field rather than at the field, which is how three of these hid.
    """
    from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QLineEdit

    buddied = {id(lbl.buddy()) for lbl in root.findChildren(QLabel) if lbl.buddy()}
    fields = [w for kind in (QLineEdit, QComboBox) for w in root.findChildren(kind)
              # A spin box builds its own QLineEdit to edit in. That editor belongs to Qt, not to
              # anybody's form, and naming it is not how a spin box becomes accessible: the label
              # buddies the spin box itself, which is what a screen reader reaches. Counting the
              # child would demand a name for a widget the developer never created.
              if not isinstance(w.parent(), QAbstractSpinBox)]
    return [f"{type(w).__name__} ({w.accessibleName() or w.toolTip()[:30]!r})"
            for w in fields
            if not w.accessibleName() and id(w) not in buddied]


def test_no_field_in_the_window_is_left_unnamed(qapp, make_view):
    window = make_view(MainWindow)
    window.set_advanced_mode(True)
    assert _unnamed_fields(window) == []


def test_no_field_in_the_settings_dialog_is_left_unnamed(qapp, qtbot):
    from firmauy_desktop.settings import Settings
    from firmauy_desktop.views.settings_dialog import SettingsDialog

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    assert _unnamed_fields(dialog) == []


def test_the_pin_field_is_named_by_the_prompt_that_asks_for_it(qapp, qtbot):
    """Not a child of the window either, and the one field everybody who signs types into."""
    from firmauy_desktop.dialogs import _PinDialog

    dialog = _PinDialog(None, "PIN de la cédula", "Ingresá el PIN para firmar contrato.pdf:")
    qtbot.addWidget(dialog)
    assert _unnamed_fields(dialog) == []


def test_no_label_in_the_settings_dialog_is_left_on_autotext(qapp, qtbot):
    """The window is walked by test_theming. This dialog is not a child of it, so its own form
    rows went on building AutoText labels for themselves until now."""
    from firmauy_desktop.settings import Settings
    from firmauy_desktop.views.settings_dialog import SettingsDialog

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    offenders = [lbl.text()[:40] for lbl in dialog.findChildren(QLabel)
                 if lbl.textFormat() != Qt.TextFormat.PlainText]
    assert offenders == []


def test_the_drop_area_says_what_it_is_holding(qapp):
    """The description was set once at construction and never again, so a screen reader on a
    loaded drop area still read out "arrastrá un archivo acá"."""
    area = DropArea("Arrastrá un archivo acá")
    prompt = area.accessibleDescription()

    area.show_files(["/home/ana/contrato.pdf"])

    assert area.accessibleDescription() != prompt
    assert "contrato.pdf" in area.accessibleDescription()

    area.reset()
    assert area.accessibleDescription() == prompt
