# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the sign screen, against a stand-in backend. No card, no PIN, no modal.

Widget visibility is asserted with ``isHidden()``: ``isVisible()`` is always False when no
window has been shown, so it would pass for the wrong reason.
"""

from __future__ import annotations


import threading

import pytest

from conftest import widget_text
from firmauy_desktop import backend
from firmauy_desktop.views import sign_view


def _ok(output: str = "/tmp/doc.pdf.p7s") -> backend.SignResult:
    return backend.SignResult(True, output, output)


def test_choosing_a_file_enables_the_button(make_view, qtbot, fake_backend):
    view = make_view(sign_view.SignView)

    assert view._button.isEnabled() is False
    view.load("/tmp/doc.pdf")
    assert view._button.isEnabled() is True


def test_the_pin_is_asked_only_after_the_card_checks_out(make_view, qtbot, fake_backend, monkeypatch):
    """The invariant CONTRIBUTING cares most about: a setup that cannot sign never costs a try.

    The stand-in mimics firmauy's order: it gets all the way through the reader, card and
    certificate checks, and only then calls back for the PIN.
    """
    order = []

    def fake_sign(path, pin=None, *, pin_provider=None, native=True, **kw):
        order.append("card checked")
        order.append(f"pin: {pin_provider()}")
        return _ok()

    fake_backend.patch(sign_view, "sign_file", side_effect=fake_sign)
    monkeypatch.setattr(sign_view, "ask_pin",
                        lambda parent, **kw: (order.append("prompt"), "1234")[1])

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert order == ["card checked", "prompt", "pin: 1234"]
    assert widget_text(view._status) == "Firmado: /tmp/doc.pdf.p7s"
    assert view._status.property("tone") == "ok"
    assert view._open_btn.isHidden() is False


def test_the_pin_is_never_passed_up_front(make_view, qtbot, fake_backend, monkeypatch):
    fake_backend.patch(sign_view, "sign_file", _ok())
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    kwargs = fake_backend.kwargs_for("sign_file")
    assert "pin" not in kwargs                       # never collected before the card is ready
    assert callable(kwargs["pin_provider"])


def test_cancelling_the_prompt_cancels_the_signature(make_view, qtbot, fake_backend, monkeypatch):
    def fake_sign(path, pin=None, *, pin_provider=None, native=True, **kw):
        try:
            pin_provider()
        except backend.PinCancelled:
            return backend.SignResult(False, None, "Firma cancelada.")
        raise AssertionError("the provider should have raised")

    fake_backend.patch(sign_view, "sign_file", side_effect=fake_sign)
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: None)

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert widget_text(view._status) == "Firma cancelada."
    assert view._open_btn.isHidden() is True
    assert view._button.isEnabled() is True          # the inputs came back


def test_a_failure_is_shown_and_the_folder_button_stays_hidden(make_view, qtbot, fake_backend, monkeypatch):
    fake_backend.patch(sign_view, "sign_file",
                       backend.SignResult(False, None, "PIN incorrecto. Te quedan 2 intentos."))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "0000")

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert widget_text(view._status) == "PIN incorrecto. Te quedan 2 intentos."
    assert view._status.property("tone") == "bad"
    assert view._open_btn.isHidden() is True


def test_the_inputs_lock_while_signing_and_a_second_click_is_refused(make_view, qtbot, fake_backend,
                                                                    monkeypatch):
    release = threading.Event()
    calls = []

    def fake_sign(path, pin=None, *, pin_provider=None, native=True, **kw):
        calls.append(path)
        release.wait(5)
        return _ok()

    fake_backend.patch(sign_view, "sign_file", side_effect=fake_sign)
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")

    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()
        assert view._button.isEnabled() is False     # locked mid-operation
        assert view._drop.isEnabled() is False
        view._on_sign()                              # refused, not stacked
        release.set()

    assert calls == ["/tmp/doc.pdf"]
    # Not back on: the file is signed. Pressing Firmar again would sign the same file onto an
    # output that now exists and land on the replace dialog, so it waits for a new selection.
    assert view._button.isEnabled() is False
    assert view._drop.isEnabled() is True


def test_shutdown_releases_a_worker_parked_on_the_prompt(make_view, qtbot, fake_backend, monkeypatch):
    """Closing the window used to leave the thread running until the 300s PIN timeout."""
    reached = threading.Event()

    def fake_sign(path, pin=None, *, pin_provider=None, native=True, **kw):
        reached.set()
        try:
            pin_provider()
        except backend.PinCancelled:
            return backend.SignResult(False, None, "Firma cancelada.")
        raise AssertionError("the provider should have raised")

    fake_backend.patch(sign_view, "sign_file", side_effect=fake_sign)

    view = make_view(sign_view.SignView)
    view._pin.requested.disconnect()                 # nobody answers the prompt
    view.load("/tmp/doc.pdf")
    view._on_sign()
    assert reached.wait(5)

    view.shutdown()                                  # must not wait out the PIN timeout
    assert view._runner.busy is False


def test_the_settings_reach_the_signature(make_view, qtbot, fake_backend, monkeypatch):
    """Ajustes is only real if what it stores actually shows up in the call."""
    from firmauy_desktop import settings

    settings.save(settings.Settings(
        native=False, pkcs11_lib="/lib.so", reader="ACS",
        tsa_url="https://tsa.example.uy", verify_after_sign=False,
    ))
    fake_backend.patch(sign_view, "sign_file", _ok())
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    kwargs = fake_backend.kwargs_for("sign_file")
    assert kwargs["native"] is False
    assert kwargs["pkcs11_lib"] == "/lib.so"
    assert kwargs["reader"] == "ACS"
    assert kwargs["tsa_url"] == "https://tsa.example.uy"
    assert kwargs["verify"] is False


def test_a_change_in_ajustes_applies_to_the_next_signature(make_view, qtbot, fake_backend,
                                                           monkeypatch):
    """The settings are read when signing starts, not when the screen is built, so a change
    does not wait for a restart."""
    from firmauy_desktop import settings

    fake_backend.patch(sign_view, "sign_file", _ok())
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)                     # built with the defaults
    view.load("/tmp/doc.pdf")

    settings.save(settings.Settings(native=False))           # changed afterwards
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert fake_backend.kwargs_for("sign_file")["native"] is False


# --- the advanced options ---------------------------------------------------

def _signed(**kw) -> backend.SignResult:
    base = dict(ok=True, output_path="/tmp/doc_firmado.pdf", detail="/tmp/doc_firmado.pdf")
    base.update(kw)
    return backend.SignResult(**base)


def test_the_advanced_panel_starts_folded(make_view, qtbot, fake_backend):
    """One drop and one button is the whole primary flow. Nobody signing a contract needs to
    decide on a timestamping authority to do it."""
    view = make_view(sign_view.SignView)
    assert view._sign_as.currentData() == "auto"
    assert view._output_dir.text() == ""


def test_forcing_a_signature_type_reaches_the_call(make_view, qtbot, fake_backend, monkeypatch):
    fake_backend.patch(sign_view, "sign_file", _signed())
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/contrato.pdf")
    view._sign_as.setCurrentIndex(view._sign_as.findData("cades"))
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert fake_backend.kwargs_for("sign_file")["sign_as"] == "cades"


def test_motivo_and_lugar_only_apply_to_a_pdf(make_view, qtbot, fake_backend):
    """They go into the PAdES metadata, so they mean nothing anywhere else."""
    view = make_view(sign_view.SignView)
    assert view._reason.isEnabled() is True              # auto could still resolve to a PDF

    view._sign_as.setCurrentIndex(view._sign_as.findData("xml"))
    assert view._reason.isEnabled() is False
    assert view._location.isEnabled() is False

    view._sign_as.setCurrentIndex(view._sign_as.findData("pdf"))
    assert view._reason.isEnabled() is True


def test_a_disabled_motivo_is_not_sent(make_view, qtbot, fake_backend, monkeypatch):
    fake_backend.patch(sign_view, "sign_file", _signed())
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/factura.xml")
    view._reason.setText("algo")
    view._sign_as.setCurrentIndex(view._sign_as.findData("xml"))
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert "reason" not in fake_backend.kwargs_for("sign_file")


_PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer<<>>\n%%EOF\n"


def test_the_output_folder_gets_the_name_firmauy_would_use(make_view, qtbot, fake_backend,
                                                           monkeypatch, tmp_path):
    """This asserted `/tmp/firmados/contrato.pdf` for years, which is the input's own name.

    The rule belongs to firmauy and the app was reimplementing it: a PDF signed into a folder
    becomes `contrato_firmado.pdf`, and aiming at `contrato.pdf` meant aiming at the original.
    The batch path never had the bug, because sign_batch is handed a folder and names the files
    itself.
    """
    source = tmp_path / "contrato.pdf"
    source.write_bytes(_PDF)
    folder = tmp_path / "firmados"
    folder.mkdir()
    fake_backend.patch(sign_view, "sign_file", _signed())
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load(str(source))
    view._output_dir.setText(str(folder))
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert fake_backend.kwargs_for("sign_file")["output"] == str(folder / "contrato_firmado.pdf")


def test_forcing_a_detached_signature_does_not_write_cms_into_a_pdf(make_view, qtbot,
                                                                    fake_backend, monkeypatch,
                                                                    tmp_path):
    """The worst shape of the same bug: the file would have been named .pdf and held CMS."""
    source = tmp_path / "contrato.pdf"
    source.write_bytes(_PDF)
    folder = tmp_path / "firmados"
    folder.mkdir()
    fake_backend.patch(sign_view, "sign_file", _signed())
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load(str(source))
    view._output_dir.setText(str(folder))
    view._sign_as.setCurrentIndex(view._sign_as.findData("cades"))
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert fake_backend.kwargs_for("sign_file")["output"] == str(folder / "contrato.pdf.p7s")


def test_a_folder_that_cannot_be_resolved_stops_before_the_card(make_view, qtbot, fake_backend,
                                                                monkeypatch, tmp_path):
    """Detecting the type means reading the file, and that can fail.

    Falling back to letting firmauy choose was the first fix, and it was wrong: a folder was
    picked and the signature would have gone somewhere else without a word. A signed file quietly
    landing in the wrong place is not a smaller problem than not signing, so this refuses, and it
    refuses before the card is acquired.
    """
    fake_backend.patch(sign_view, "sign_file", _signed())
    monkeypatch.setattr(sign_view, "ask_pin",
                        lambda parent, **kw: pytest.fail("the PIN must never be asked"))

    view = make_view(sign_view.SignView)
    view.load(str(tmp_path / "no-existe.pdf"))
    view._output_dir.setText(str(tmp_path))
    view._on_sign()

    assert fake_backend.calls == []
    assert view._card.busy is False
    assert "No se pudo resolver dónde guardarlo" in widget_text(view._status)
    assert view._status.property("tone") == "bad"


def test_no_folder_chosen_still_leaves_the_name_to_firmauy(make_view, qtbot, fake_backend,
                                                           monkeypatch):
    """The refusal above is about a folder that was picked. With none, there is nothing to
    honour and firmauy decides, which is what it has always done."""
    fake_backend.patch(sign_view, "sign_file", _signed())
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert fake_backend.kwargs_for("sign_file")["output"] is None


def test_an_empty_tsa_field_leaves_the_one_from_ajustes(make_view, qtbot, fake_backend,
                                                        monkeypatch):
    """The field is a per-signature override, so Ajustes stays the source of truth."""
    from firmauy_desktop import settings

    settings.save(settings.Settings(tsa_url="https://tsa.ajustes.uy"))
    fake_backend.patch(sign_view, "sign_file", _signed())
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()
    assert fake_backend.kwargs_for("sign_file")["tsa_url"] == "https://tsa.ajustes.uy"

    view._tsa.setText("https://tsa.esta.vez")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()
    assert fake_backend.kwargs_for("sign_file")["tsa_url"] == "https://tsa.esta.vez"


# --- what came out ----------------------------------------------------------

def test_the_report_says_which_kind_came_out(make_view, qtbot, fake_backend, monkeypatch):
    """"Firmado" alone does not say which of the three kinds was produced, nor whether the app
    re-read its own work."""
    fake_backend.patch(sign_view, "sign_file", _signed(
        kind="pades", backend="native", signer="PEREZ PEREZ JUAN",
        certificate_serial="781910B3", verified=True))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    details = widget_text(view._report)
    assert "PDF firmado (PAdES)" in details
    assert "PEREZ PEREZ JUAN" in details
    assert "modo directo" in details
    assert "781910B3" in details
    assert "se releyó" in details


def test_the_report_is_cleared_before_the_next_signature(make_view, qtbot, fake_backend,
                                                         monkeypatch):
    fake_backend.patch(sign_view, "sign_file", _signed(kind="pades"))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()
    assert widget_text(view._report) != ""

    view.load("/tmp/otro.pdf")
    assert widget_text(view._report) == ""               # no stale report from the last one
    assert view._report.isHidden() is False              # empty, not merely hidden


# --- an output that is already there ----------------------------------------

def test_an_existing_output_offers_to_replace_it(make_view, qtbot, fake_backend, monkeypatch):
    """Asked at the collision rather than armed as a checkbox beforehand: the same capability,
    with a safe default, and the person sees the name of what is about to go."""
    attempts = []

    def fake_sign(path, pin=None, **kw):
        attempts.append(kw.get("overwrite"))
        if len(attempts) == 1:
            return backend.SignResult(False, None, "Ya existe doc_firmado.pdf.",
                                      "output_exists", conflict_path="/tmp/doc_firmado.pdf")
        return _signed()

    fake_backend.patch(sign_view, "sign_file", side_effect=fake_sign)
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    asked = []
    monkeypatch.setattr(sign_view, "confirm_overwrite",
                        lambda parent, path: asked.append(path) or True)

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()
    # The retry is a second run started from inside the done-slot, so wait for its result rather
    # than for the call: the button is what proves the second one landed.
    qtbot.waitUntil(lambda: not view._open_btn.isHidden(), timeout=5000)

    assert asked == ["/tmp/doc_firmado.pdf"]             # the dialog named the file
    assert attempts == [False, True]                     # the retry asked to overwrite


def test_declining_the_replacement_leaves_the_file_alone(make_view, qtbot, fake_backend,
                                                         monkeypatch):
    attempts = []

    def fake_sign(path, pin=None, **kw):
        attempts.append(kw.get("overwrite"))
        return backend.SignResult(False, None, "Ya existe doc_firmado.pdf.",
                                  "output_exists", conflict_path="/tmp/doc_firmado.pdf")

    fake_backend.patch(sign_view, "sign_file", side_effect=fake_sign)
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")
    monkeypatch.setattr(sign_view, "confirm_overwrite", lambda parent, path: False)

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert attempts == [False]                           # nothing was overwritten
    assert "Ya existe" in widget_text(view._status)
    assert view._card.busy is False                      # and the card was handed back


def test_another_failure_does_not_trigger_the_replace_dialog(make_view, qtbot, fake_backend,
                                                             monkeypatch):
    fake_backend.patch(sign_view, "sign_file",
                       backend.SignResult(False, None, "PIN incorrecto.", "pin"))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "0000")
    monkeypatch.setattr(sign_view, "confirm_overwrite",
                        lambda parent, path: pytest.fail("must not be asked"))

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert widget_text(view._status) == "PIN incorrecto."


def test_the_button_itself_works(make_view, qtbot, fake_backend, monkeypatch):
    """QPushButton.clicked passes a `checked` bool, and _on_sign grew a parameter. Every other
    test calls the slot directly, so this is the only one that would catch the mismatch."""
    from PySide6.QtCore import Qt as _Qt

    fake_backend.patch(sign_view, "sign_file", _signed())
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        qtbot.mouseClick(view._button, _Qt.MouseButton.LeftButton)

    assert view._open_btn.isHidden() is False
    assert fake_backend.kwargs_for("sign_file")["overwrite"] is False


def test_the_options_are_frozen_while_a_signature_is_in_flight(make_view, qtbot, fake_backend,
                                                               monkeypatch):
    """Every option is read at the moment run() is called, so changing one halfway cannot alter
    what is being written. A panel that still takes edits says otherwise."""
    fake_backend.patch(sign_view, "sign_file", _signed())
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    assert view._options_panel.isEnabled() is True

    view._set_busy(True)
    assert view._options_panel.isEnabled() is False
    view._set_busy(False)
    assert view._options_panel.isEnabled() is True


def test_a_new_selection_is_refused_while_signing(make_view, qtbot, fake_backend, monkeypatch):
    """_set_busy disables the drop area and the button, but the Archivo menu reaches load()
    directly. Swapping the selection under a running batch would leave the per-file rows about
    one set of files and _paths naming another."""
    import threading

    started = threading.Event()

    def slow(*a, **kw):
        started.set()
        return _signed()

    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")
    monkeypatch.setattr(sign_view, "sign_file", slow)

    view = make_view(sign_view.SignView)
    view.load("/tmp/a.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()
        view.load("/tmp/b.pdf")          # as the menu would, mid-run

    assert view._paths == ["/tmp/a.pdf"]


# --- what the screen offers once something has been signed -------------------

def test_firmar_steps_down_once_the_file_is_signed(make_view, qtbot, fake_backend, monkeypatch):
    """The blue button kept dominating a screen whose operation was over, and pressing it again
    signed the same file onto an output that now exists, straight into the replace dialog."""
    fake_backend.patch(sign_view, "sign_file", _signed())
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    assert view._button.property("variant") == "primary"

    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert view._button.isEnabled() is False
    assert view._button.property("variant") is None       # no longer the loudest thing on it
    assert view._verify_btn.property("variant") == "primary"
    assert view._verify_btn.isHidden() is False
    assert view._again_btn.isHidden() is False


def test_a_new_selection_makes_firmar_the_answer_again(make_view, qtbot, fake_backend,
                                                       monkeypatch):
    fake_backend.patch(sign_view, "sign_file", _signed())
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    view.load("/tmp/otro.pdf")

    assert view._button.isEnabled() is True
    assert view._button.property("variant") == "primary"
    assert view._verify_btn.isHidden() is True


def test_firmar_otro_archivo_puts_the_screen_back(make_view, qtbot, fake_backend, monkeypatch):
    fake_backend.patch(sign_view, "sign_file", _signed())
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    view._start_over()

    assert view._paths == []
    assert view._button.isEnabled() is False              # nothing selected to sign
    assert widget_text(view._report) == ""
    assert view._verify_btn.isHidden() is True
    assert "Arrastrá" in view._drop._label.text()         # the prompt is back


def test_a_signed_file_whose_permissions_failed_is_not_shown_as_a_failure(make_view, qtbot,
                                                                          fake_backend,
                                                                          monkeypatch):
    """The one failure that leaves a document behind. It is written, complete and readable by its
    owner, and only its permissions are wrong. Shown in red with no buttons it reads as "nothing
    came out of this", and the obvious response to that is to sign it again, which is exactly
    what the message asks the person not to do."""
    def fake_sign(path, pin=None, **kw):
        return backend.SignResult(
            False, "/tmp/doc_firmado.pdf",
            "doc_firmado.pdf se firmó y quedó guardado, pero no se le pudieron poner los "
            "permisos que correspondían. Arreglá los permisos en lugar de firmar de nuevo.",
            "output_committed")

    fake_backend.patch(sign_view, "sign_file", side_effect=fake_sign)
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert view._status.property("tone") == "warn", "a signed document was painted as a failure"
    assert "Arreglá los permisos" in widget_text(view._status)
    assert view._open_btn.isHidden() is False, "the file exists and cannot be opened"
    assert view._verify_btn.isHidden() is False
    assert view._output_path == "/tmp/doc_firmado.pdf"


def test_an_unexpected_crash_points_at_the_record_it_can_actually_be_read_in(
    make_view, qtbot, fake_backend,
):
    """The screen asks the record what its state is, rather than assuming one.

    This is the wiring, not the wording: labels owns the two sentences and is tested there. What
    is worth proving here is that the view passes the live state, so the branch a person meets
    matches the record they actually have.
    """
    from firmauy_desktop import activity

    view = make_view(sign_view.SignView)

    activity.configure(False)
    view._on_crash()
    off = widget_text(view._status)

    activity.configure(True)
    view._on_crash()
    on = widget_text(view._status)

    assert "consola" not in off and "consola" not in on
    assert "activá el registro de actividad" in off
    assert "Quedó anotado en el registro de actividad" in on
    assert view._status.property("tone") == "bad"


# --- the PIN dialog and the pointer to the State validator -------------------

def test_the_pin_dialog_says_what_it_authorizes(make_view, qtbot, monkeypatch):
    """The most sensitive dialog in the app binds the PIN to what it is paying for: the file
    by name, or the batch by size. A person should get to expect that whatever asks for the
    PIN says what it is for."""
    assert sign_view._pin_prompt(["/tmp/factura.pdf"]) == (
        "Ingresá el PIN para firmar factura.pdf:")
    assert sign_view._pin_prompt(["/a.pdf", "/b.xml", "/c.bin"]) == (
        "Ingresá el PIN para firmar los 3 archivos:")

    seen = []
    monkeypatch.setattr(sign_view, "ask_pin",
                        lambda parent, **kw: seen.append(kw.get("prompt")) or None)
    view = make_view(sign_view.SignView)
    view._pin_prompt = "Ingresá el PIN para firmar los 2 archivos:"
    view._ask_pin()

    assert seen == ["Ingresá el PIN para firmar los 2 archivos:"]


def test_a_fresh_signature_comes_with_the_pointer_to_the_state_validator(make_view, qtbot,
                                                                         fake_backend,
                                                                         monkeypatch):
    """"Cross-check what you sign" is about the document just produced. Whoever signs and
    sends without passing through Verificar meets the arbiter here or never."""
    fake_backend.patch(sign_view, "sign_file", _signed(kind="pades"))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    assert view._report_validator.isHidden() is True

    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert view._report_validator.isHidden() is False
    assert "firma.gub.uy" in widget_text(view._report_validator)

    view.load("/tmp/otro.pdf")
    assert view._report_validator.isHidden() is True     # no stale claim over the next file
