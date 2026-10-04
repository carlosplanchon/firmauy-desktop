# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""The PIN prompt: what it shows, what it lets through, and what it leaves behind.

It replaced QInputDialog.getText, whose prompt label was AutoText while it named the file about
to be signed, and which let any PIN through to fail inside firmauy after the signature had begun.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QDialog, QLabel, QWidget

from firmauy_desktop import backend, dialogs
from firmauy_desktop.views.sign_view import _pin_prompt

# A valid file name on Linux, which is why every tag is left open: a closing tag needs a slash.
# Against the QInputDialog this sentence came out large and red, inside the PIN prompt.
_HOSTILE = ("contrato.pdf<br><br><font size=6 color=red>Tu cédula se bloqueó. "
            "Escribí el PUK en vez del PIN.pdf")


def _dialog(qtbot, prompt: str = "Ingresá el PIN:") -> "dialogs._PinDialog":
    made = dialogs._PinDialog(None, "PIN de la cédula", prompt)
    qtbot.addWidget(made)
    return made


def test_the_prompt_shows_a_file_name_as_written(qtbot):
    prompt = _pin_prompt([f"/home/ana/{_HOSTILE}"])
    made = _dialog(qtbot, prompt)

    labels = made.findChildren(QLabel)
    assert [lbl.textFormat() for lbl in labels] == [Qt.TextFormat.PlainText] * len(labels)
    assert prompt in [lbl.text() for lbl in labels]         # intact, tags and all


@pytest.mark.parametrize("typed, accepts, tone", [
    ("", False, "muted"),
    ("123", False, "muted"),            # on its way to four: no red at every keystroke
    ("1234", True, "muted"),
    ("12345678", True, "muted"),
    ("123456789", False, "bad"),
    ("12a4", False, "bad"),
    ("١٢٣٤", False, "bad"),
], ids=["empty", "short", "four", "eight", "nine", "letter", "arabic-indic"])
def test_aceptar_waits_for_a_pin_the_card_could_take(qtbot, typed, accepts, tone):
    made = _dialog(qtbot)
    made._field.setText(typed)

    assert made._ok.isEnabled() is accepts
    assert made._hint.property("tone") == tone
    # The hint is what explains a button that does nothing, so a screen reader gets it too.
    assert made._field.accessibleDescription() == made._hint.text()


def test_what_was_typed_is_what_it_holds(qtbot):
    """Nothing dropped and nothing cut as it arrives. Behind a field of dots, a letter left out
    or a ninth digit trimmed would send a PIN the person never typed, and the card counts that
    as a wrong one. Refusing to accept it costs nothing."""
    made = _dialog(qtbot)
    qtbot.keyClicks(made._field, "12a456789")

    assert made.pin() == "12a456789"
    assert not made._ok.isEnabled()


def test_ask_pin_hands_back_exactly_the_pin(qtbot, monkeypatch):
    def type_and_accept(self):
        self._field.setText("0042")         # leading zeros are part of a PIN
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs._PinDialog, "exec", type_and_accept)
    assert dialogs.ask_pin(None) == "0042"


def test_dismissing_it_is_no_pin(qtbot, monkeypatch):
    monkeypatch.setattr(dialogs._PinDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    assert dialogs.ask_pin(None) is None


def test_the_dialog_does_not_outlive_the_answer(qtbot, monkeypatch):
    """A child of the screen that opened it would have kept the PIN in its field until the
    window closed, which is not what "nothing here keeps the PIN" says."""
    def type_and_accept(self):
        self._field.setText("1234")
        return QDialog.DialogCode.Accepted

    screen = QWidget()
    qtbot.addWidget(screen)
    monkeypatch.setattr(dialogs._PinDialog, "exec", type_and_accept)

    assert dialogs.ask_pin(screen) == "1234"
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert screen.findChildren(dialogs._PinDialog) == []


@pytest.mark.parametrize("pin", [
    "", "1", "123", "1234", "0000", "12345678", "123456789", "12a4", " 1234", "1234 ", "+1234",
    "١٢٣٤", "１２３４", "²²²²", "①②③④",
])
def test_the_app_and_firmauy_agree_on_what_a_pin_is(pin):
    """Never stricter: a PIN the dialog turned away and firmauy would have sent is a card nobody
    could sign with from here. Never looser either, or the dialog lets through what firmauy then
    refuses after the signature has started, which is what it exists to stop.

    firmauy's rule is reached through an internal on purpose. It is the rule itself, which no
    public call exposes without a card, and a rename upstream fails here, loudly, which is the
    right moment to look at both again.
    """
    from firmauy.api import PinError
    from firmauy.signing import _resolve_final_pin

    try:
        _resolve_final_pin(pin, None)
        firmauy_sends = True
    except PinError:
        firmauy_sends = False

    assert (backend.pin_shape(pin) == "ok") is firmauy_sends
