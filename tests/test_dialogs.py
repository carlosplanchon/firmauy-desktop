# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Every button in the app's dialogs is named by the app.

A standard button left alone says whatever Qt says. Before the app loaded Qt's translation that
was OK, Yes, Cancel or Close, in English, in an app that is Spanish everywhere else: "Ya existe"
asked "¿Lo reemplazo?" over Yes and Cancel, and Acerca de closed with OK. The translation fixes
the language and not the choice of word, and it is a file a Qt can lack, so the dialogs still
name every button. These run without it, as the suite does, which is what makes Qt's own words
something to compare against.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialogButtonBox, QMessageBox, QPushButton

from firmauy_desktop import dialogs


def _qts_own_words() -> set[str]:
    """What Qt calls each standard button when nobody names it, asked of Qt rather than listed,
    so the set is whatever this Qt says and not what a test remembered it saying."""
    words = set()
    for standard in QDialogButtonBox.StandardButton:
        box = QDialogButtonBox(standard)        # held: a temporary takes its button with it
        made = box.button(standard)
        if made is not None:
            words.add(made.text())
    return words


def _shown_box(monkeypatch, show) -> QMessageBox:
    boxes = []
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda self: boxes.append(self) or QMessageBox.StandardButton.Cancel)
    show()
    return boxes[0]


def _dialog(name, qtbot, monkeypatch):
    if name == "confirm_overwrite":
        return _shown_box(monkeypatch, lambda: dialogs.confirm_overwrite(None, "/tmp/a.pdf.p7s"))
    if name == "confirm_batch_conflicts":
        return _shown_box(monkeypatch, lambda: dialogs.confirm_batch_conflicts(
            None, [("/tmp/a.pdf", "/tmp/a-firmado.pdf")], 3))
    if name == "about_dialog":
        return _shown_box(monkeypatch, lambda: dialogs.about_dialog(None))
    if name == "pin":
        made = dialogs._PinDialog(None, "PIN de la cédula", "Ingresá el PIN:")
    else:
        from firmauy_desktop.settings import Settings
        from firmauy_desktop.views.settings_dialog import SettingsDialog

        made = SettingsDialog(Settings())
    qtbot.addWidget(made)
    return made


def test_qt_really_names_them_in_english_here():
    """The premise. With a translation loaded this set would be Spanish, the test below would
    pass whatever the dialogs said, and this is what would notice."""
    assert {"OK", "Cancel"} <= _qts_own_words() or {"&OK", "&Cancel"} <= _qts_own_words()


@pytest.mark.parametrize("name", ["confirm_overwrite", "confirm_batch_conflicts", "about_dialog",
                                  "pin", "settings"])
def test_no_button_is_left_with_qts_own_word_for_it(qtbot, monkeypatch, name):
    dialog = _dialog(name, qtbot, monkeypatch)
    texts = [button.text() for button in dialog.findChildren(QPushButton)]

    assert texts, "no buttons at all, so nothing here was checked"
    assert set(texts).isdisjoint(_qts_own_words()), f"{name}: {texts}"


def test_replacing_is_the_named_choice_and_cancelling_the_default(monkeypatch):
    """The words moved, so what each one does is held too: "Reemplazar" is the only way to a
    yes, and the button Enter presses is the one that keeps the existing file."""
    def press(label):
        def exec_(self):
            return self.standardButton(next(b for b in self.buttons() if b.text() == label))
        return exec_

    monkeypatch.setattr(QMessageBox, "exec", press("Reemplazar"))
    assert dialogs.confirm_overwrite(None, "/tmp/a.pdf.p7s") is True
    monkeypatch.setattr(QMessageBox, "exec", press("Cancelar"))
    assert dialogs.confirm_overwrite(None, "/tmp/a.pdf.p7s") is False

    boxes = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: boxes.append(self) or 0)
    dialogs.confirm_overwrite(None, "/tmp/a.pdf.p7s")
    assert boxes[0].defaultButton().text() == "Cancelar"
