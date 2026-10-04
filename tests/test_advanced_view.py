# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the Avanzado screen and the mode that reveals it."""

from __future__ import annotations

from conftest import widget_text
from firmauy_desktop import backend, settings
from firmauy_desktop.main_window import MainWindow
from firmauy_desktop.views import advanced_view

_PEM = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"


def _cert(**kw) -> backend.Cert:
    base = dict(
        id="5c10d3cb", subject_common_name="PEREZ PEREZ JUAN",
        subject_serial_number="DNI12345672",
        issuer_common_name="Autoridad Certificadora del Ministerio del Interior",
        certificate_serial="781910B3", not_after="2031-03-25",
        digital_signature=True, pem=_PEM,
    )
    base.update(kw)
    return backend.Cert(**base)


def _patch(fake_backend, tokens=None, certs=None):
    fake_backend.patch(advanced_view, "list_tokens", backend.Result(True, tokens if tokens
                                                                    is not None else []))
    fake_backend.patch(advanced_view, "list_certs", backend.Result(True, certs if certs
                                                                   is not None else []))


def _read(qtbot, view):
    with qtbot.waitSignal(view._certs_runner.finished, timeout=5000):
        view._on_read()


def test_reading_shows_the_token_and_its_certificate(make_view, qtbot, fake_backend):
    _patch(fake_backend,
           tokens=[backend.Token("GemP15-1", "", "Classic V4", "66000034D0201077")],
           certs=[_cert()])

    view = make_view(advanced_view.AdvancedView)
    _read(qtbot, view)

    tokens = widget_text(view._token_list)
    assert "GemP15-1" in tokens
    assert "Classic V4" in tokens
    assert "66000034D0201077" in tokens
    # Never a Python bytes repr. firmauy leaked one out of token_to_dict once, and with plain
    # text there is no escaping left to hide it behind.
    assert "b'" not in tokens

    cert = widget_text(view._cert)
    assert "PEREZ PEREZ JUAN" in cert
    assert "DNI12345672" in cert
    assert "2031-03-25" in cert
    assert view._picker.count() == 1


def test_no_token_says_so_instead_of_showing_nothing(make_view, qtbot, fake_backend):
    _patch(fake_backend, tokens=[], certs=[])

    view = make_view(advanced_view.AdvancedView)
    _read(qtbot, view)

    assert "ningún token" in widget_text(view._status)
    assert view._save_btn.isEnabled() is False


def test_several_certificates_can_be_picked_between(make_view, qtbot, fake_backend):
    _patch(fake_backend, tokens=[backend.Token("T")],
           certs=[_cert(subject_common_name="FIRMA"), _cert(subject_common_name="AUTENTICACIÓN")])

    view = make_view(advanced_view.AdvancedView)
    _read(qtbot, view)

    assert [view._picker.itemText(i) for i in range(2)] == ["FIRMA", "AUTENTICACIÓN"]
    view._picker.setCurrentIndex(1)
    assert "AUTENTICACIÓN" in widget_text(view._cert)


def test_saving_the_pem_writes_the_public_certificate(make_view, qtbot, fake_backend,
                                                      monkeypatch, tmp_path):
    """A real errand: handing your public certificate to whoever has to verify your signatures."""
    _patch(fake_backend, tokens=[backend.Token("T")], certs=[_cert()])

    view = make_view(advanced_view.AdvancedView)
    _read(qtbot, view)

    target = tmp_path / "mi_certificado.pem"
    monkeypatch.setattr(advanced_view.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    view._save_pem()

    assert target.read_text() == _PEM
    assert "PRIVATE KEY" not in target.read_text()    # the key never leaves the card


def test_a_certificate_without_a_pem_cannot_be_saved(make_view, qtbot, fake_backend):
    _patch(fake_backend, tokens=[backend.Token("T")], certs=[_cert(pem=None)])

    view = make_view(advanced_view.AdvancedView)
    _read(qtbot, view)

    assert view._save_btn.isEnabled() is False


def test_a_module_that_does_not_load_says_why(make_view, qtbot, fake_backend):
    fake_backend.patch(advanced_view, "list_tokens",
                       backend.Result(False, None, "no such file: /lib.so", "other"))

    view = make_view(advanced_view.AdvancedView)
    with qtbot.waitSignal(view._tokens.finished, timeout=5000):
        view._on_read()

    assert "no such file" in widget_text(view._status)
    assert view._status.property("tone") == "bad"      # an error does not look like a reading
    assert view._button.isEnabled() is True           # ready to try again
    assert view._card.busy is False                   # and the card was handed back


def test_it_uses_the_module_configured_in_ajustes(make_view, qtbot, fake_backend):
    """Not a separate choice, so what this screen reports is what signing would use."""
    settings.save(settings.Settings(pkcs11_lib="/usr/lib/pkcs11/libgclib.so"))
    _patch(fake_backend, tokens=[backend.Token("T")], certs=[_cert()])

    view = make_view(advanced_view.AdvancedView)
    _read(qtbot, view)

    assert fake_backend.kwargs_for("list_tokens")["pkcs11_lib"] == "/usr/lib/pkcs11/libgclib.so"
    assert fake_backend.kwargs_for("list_certs")["pkcs11_lib"] == "/usr/lib/pkcs11/libgclib.so"
    assert "libgclib.so" in widget_text(view._module)


def test_it_never_asks_for_a_pin(make_view, qtbot, fake_backend):
    """Cédula tokens do not gate their certificate list, and a prompt would spend card tries."""
    _patch(fake_backend, tokens=[backend.Token("T")], certs=[_cert()])

    view = make_view(advanced_view.AdvancedView)
    _read(qtbot, view)

    assert "pin" not in fake_backend.kwargs_for("list_certs")


def test_a_hostile_common_name_arrives_intact(make_view, qtbot, fake_backend):
    """This screen prints whatever the card's certificate says its subject is, and that used to go
    into a RichText label. Escaped it came out mangled, unescaped it resolved a local file. Plain
    text is neither: what the certificate says is what shows up."""
    hostile = '<img src="file:///etc/passwd">JUAN <PEREZ & CIA'
    _patch(fake_backend, tokens=[backend.Token("T")],
           certs=[_cert(subject_common_name=hostile)])

    view = make_view(advanced_view.AdvancedView)
    _read(qtbot, view)

    assert hostile in widget_text(view._cert)


def test_reading_again_replaces_what_was_there(make_view, qtbot, fake_backend):
    """The failure a rebuilt container invites: the old rows stay alive underneath and the screen
    shows two tokens where the module reports one."""
    _patch(fake_backend, tokens=[backend.Token("GemP15-1")], certs=[_cert()])
    view = make_view(advanced_view.AdvancedView)
    _read(qtbot, view)

    _patch(fake_backend, tokens=[backend.Token("OtroToken")], certs=[_cert()])
    _read(qtbot, view)

    tokens = widget_text(view._token_list)
    assert "OtroToken" in tokens
    assert "GemP15-1" not in tokens


def test_a_module_that_stops_seeing_the_card_drops_the_old_token(make_view, qtbot, fake_backend):
    """Pulling the cédula out and reading again has to leave the screen empty, not still showing
    the token that is no longer in the reader."""
    _patch(fake_backend, tokens=[backend.Token("GemP15-1")], certs=[_cert()])
    view = make_view(advanced_view.AdvancedView)
    _read(qtbot, view)

    _patch(fake_backend, tokens=[], certs=[])
    _read(qtbot, view)

    assert widget_text(view._token_list) == ""
    assert "ningún token" in widget_text(view._status)


# --- the mode that reveals it -----------------------------------------------

def test_the_screen_is_built_but_hidden_by_default(make_view, qtbot):
    """Built and added unconditionally, so the headless startup check still covers it."""
    window = make_view(MainWindow)

    assert "Avanzado" in window.screen_labels()       # the app knows about it
    assert "advanced" not in window.visible_screens()  # a person cannot reach it


def test_turning_the_mode_on_reveals_it_and_is_remembered(make_view, qtbot):
    window = make_view(MainWindow)
    window.set_advanced_mode(True)

    assert "advanced" in window.visible_screens()
    assert settings.load().advanced_mode is True

    reopened = make_view(MainWindow)
    assert "advanced" in reopened.visible_screens()


def test_ajustes_is_where_the_mode_is_turned_on(make_view, qtbot, monkeypatch):
    """It used to be a checkable item in the Herramientas menu, which meant two places to
    configure the same app. It is a preference the app remembers, so it belongs with the rest."""
    from firmauy_desktop import main_window as window_module

    window = make_view(MainWindow)
    assert "advanced" not in window.visible_screens()

    saved = settings.Settings(advanced_mode=True)
    monkeypatch.setattr(window_module, "open_settings", lambda parent: saved)
    window.open_settings()

    assert "advanced" in window.visible_screens()


def test_cancelling_ajustes_changes_nothing(make_view, qtbot, monkeypatch):
    """open_settings returns None when it is cancelled, and None is not a Settings with the mode
    off: reading it as one would turn the screen off for somebody who only looked."""
    from firmauy_desktop import main_window as window_module

    window = make_view(MainWindow)
    window.set_advanced_mode(True)

    monkeypatch.setattr(window_module, "open_settings", lambda parent: None)
    window.open_settings()

    assert "advanced" in window.visible_screens()


def test_the_dialog_carries_the_mode_both_ways(qtbot):
    from firmauy_desktop.views.settings_dialog import SettingsDialog

    dialog = SettingsDialog(settings.Settings(advanced_mode=True))
    qtbot.addWidget(dialog)
    assert dialog._advanced.isChecked() is True

    dialog._advanced.setChecked(False)
    dialog._on_accept()
    assert dialog.result_settings.advanced_mode is False


def test_the_advanced_screen_shares_the_card_lock(make_view, qtbot):
    window = make_view(MainWindow)
    assert window._advanced._card is window._card


def test_the_module_is_fixed_when_the_reading_starts(make_view, qtbot, fake_backend,
                                                     monkeypatch):
    """The tokens and the certificates are one reading, chained, and settings.load() used to be
    called again for the second call. Accepting a different module in Ajustes in between would
    have the screen list one module's token beside another module's certificates.

    The token read is held open so the setting changes while the chain is genuinely in the
    middle. The first version of this test changed it afterwards, by which point list_certs had
    already been called, and it passed with the bug still in place.
    """
    import threading

    running, release = threading.Event(), threading.Event()

    def blocked(**kw):
        running.set()
        release.wait(5)
        return backend.Result(True, [backend.Token("T")])

    settings.save(settings.Settings(pkcs11_lib="/uno/libuno.so"))
    fake_backend.patch(advanced_view, "list_certs", backend.Result(True, [_cert()]))
    monkeypatch.setattr(advanced_view, "list_tokens", blocked)

    view = make_view(advanced_view.AdvancedView)
    with qtbot.waitSignal(view._certs_runner.finished, timeout=5000):
        view._on_read()
        assert running.wait(2), "the token read never started"
        settings.save(settings.Settings(pkcs11_lib="/dos/libdos.so"))   # Ajustes, mid-read
        release.set()

    assert fake_backend.kwargs_for("list_certs")["pkcs11_lib"] == "/uno/libuno.so"


def test_the_certificate_group_says_what_it_is_waiting_for(make_view, qtbot, fake_backend):
    """It used to be a disabled group holding an empty combo and a dead button, which reads as a
    broken part of the window rather than as one waiting its turn."""
    view = make_view(advanced_view.AdvancedView)

    assert "Leé el token" in widget_text(view._empty)
    assert view._picker.isHidden() is True
    assert view._save_btn.isHidden() is True
    # Not by disabling the group: that would disable the message too, and a screen reader
    # announces a disabled widget as unavailable.
    assert view._empty.isEnabled() is True


def test_reading_the_token_swaps_the_message_for_the_controls(make_view, qtbot, fake_backend):
    _patch(fake_backend, tokens=[backend.Token("T")], certs=[_cert()])

    view = make_view(advanced_view.AdvancedView)
    _read(qtbot, view)

    assert view._empty.isHidden() is True
    assert view._picker.isHidden() is False
    assert view._save_btn.isHidden() is False


def test_a_token_with_no_certificates_puts_the_message_back(make_view, qtbot, fake_backend):
    _patch(fake_backend, tokens=[backend.Token("T")], certs=[])

    view = make_view(advanced_view.AdvancedView)
    _read(qtbot, view)

    assert view._empty.isHidden() is False
    assert view._picker.isHidden() is True


def test_a_failed_second_reading_drops_the_previous_certificate(make_view, qtbot, fake_backend):
    """The certificate side is only rebuilt when the chained call comes back. A second reading
    that fails at the token step left the previous card's certificate on screen with
    "Guardar .pem..." still armed, pointing at data from a card that may not be in the reader.
    """
    _patch(fake_backend, tokens=[backend.Token("T")], certs=[_cert()])
    view = make_view(advanced_view.AdvancedView)
    _read(qtbot, view)
    assert "PEREZ PEREZ JUAN" in widget_text(view._cert)
    assert view._save_btn.isEnabled() is True

    fake_backend.patch(advanced_view, "list_tokens",
                       backend.Result(False, None, "no such file: /lib.so", "other"))
    with qtbot.waitSignal(view._tokens.finished, timeout=5000):
        view._on_read()

    assert widget_text(view._cert) == ""
    assert view._picker.count() == 0
    assert view._save_btn.isEnabled() is False
    assert view._save_btn.isHidden() is True
    assert "Leé el token" in widget_text(view._empty)
