# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the Diagnóstico screen.

The redaction test is the one that matters: this screen has a button that puts its result on the
clipboard, and one of firmauy's checks can carry the cardholder's own name.
"""

from __future__ import annotations

from conftest import widget_text
from firmauy_desktop import backend, settings
from firmauy_desktop.views import doctor_view


def _check(status="PASS", name="pcscd running", detail="", fix=None, sensitive=False):
    return backend.DoctorCheck(status, name, detail, fix, sensitive)


def _ok_result():
    return backend.DoctorResult(True, [
        _check(detail="systemd unit active"),
        _check(name="PC/SC reader detected", detail="ACS ACR38U-CCID 00 00"),
    ])


def test_checking_shows_the_result_and_offers_to_copy(make_view, qtbot, fake_backend):
    fake_backend.patch(doctor_view, "run_doctor", _ok_result())
    fake_backend.patch(doctor_view, "list_readers", backend.Result(True, []))

    view = make_view(doctor_view.DoctorView)
    assert view._copy_btn.isHidden() is True

    # The reader list, not the checks: the button is handed back when the whole chain ends.
    with qtbot.waitSignal(view._readers.finished, timeout=5000):
        view._on_check()

    assert "Todo en orden" in widget_text(view._status)
    assert view._status.property("tone") == "ok"
    assert "pcscd andando" in widget_text(view._checks)   # glossed into Spanish
    assert view._copy_btn.isHidden() is False
    assert view._button.isEnabled() is True


def test_the_copied_report_hides_what_can_identify_the_holder(make_view, qtbot, fake_backend):
    """Some PKCS#11 modules use the cardholder's name as the token label, and firmauy flags the
    checks whose detail can carry it. The clipboard is going into a support conversation."""
    fake_backend.patch(doctor_view, "run_doctor", backend.DoctorResult(True, [
        _check(detail="systemd unit active", sensitive=False),
        _check(name="cédula token detected", detail="JUANA PÉREZ GONZÁLEZ", sensitive=True),
    ]))
    fake_backend.patch(doctor_view, "list_readers", backend.Result(True, []))

    view = make_view(doctor_view.DoctorView)
    with qtbot.waitSignal(view._doctor.finished, timeout=5000):
        view._on_check()
    view._copy_report()

    from PySide6.QtGui import QGuiApplication
    copied = QGuiApplication.clipboard().text()

    assert "JUANA PÉREZ GONZÁLEZ" not in copied
    assert "[oculto: puede identificarte]" in copied
    assert "systemd unit active" in copied              # the harmless detail survives
    assert "cédula token detected" in copied            # the status is what diagnoses the setup

    # And on screen it is right there, because this is the holder's own machine. That asymmetry
    # is the whole point, and it only survives because the clipboard text is built from the
    # DoctorResult and not from the widgets: a walker over the check list cannot know which
    # detail firmauy tagged as sensitive.
    assert "JUANA PÉREZ GONZÁLEZ" in widget_text(view._checks)


def test_the_second_diagnosis_can_be_copied_too(make_view, qtbot, fake_backend):
    """Hiding the button was not enough: it came back on the next run still saying "Copiado" and
    still disabled, so only the first report of a session could ever reach the clipboard, and
    the first one is the least likely to be the one worth sending."""
    fake_backend.patch(doctor_view, "run_doctor", _ok_result())
    fake_backend.patch(doctor_view, "list_readers", backend.Result(True, []))

    view = make_view(doctor_view.DoctorView)
    # The reader list, not the checks: the card lock covers the pair and is only released when
    # the chained call comes back, so a second check before that is refused.
    with qtbot.waitSignal(view._readers.finished, timeout=5000):
        view._on_check()
    view._copy_report()
    assert view._copy_btn.isEnabled() is False          # this run is on the clipboard

    with qtbot.waitSignal(view._readers.finished, timeout=5000):
        view._on_check()

    assert view._copy_btn.isEnabled() is True
    assert view._copy_btn.text() == "Copiar diagnóstico"


def test_a_check_without_the_flag_is_treated_as_sensitive(make_view, qtbot, fake_backend):
    """An older firmauy should cost detail, not privacy."""
    fake_backend.patch(doctor_view, "run_doctor",
                       backend.DoctorResult(True, [_check(detail="algo", sensitive=True)]))
    fake_backend.patch(doctor_view, "list_readers", backend.Result(True, []))

    view = make_view(doctor_view.DoctorView)
    with qtbot.waitSignal(view._doctor.finished, timeout=5000):
        view._on_check()
    view._copy_report()

    from PySide6.QtGui import QGuiApplication
    assert "algo" not in QGuiApplication.clipboard().text()


def test_the_reader_list_fills_in_after_a_check(make_view, qtbot, fake_backend):
    """The combo is populated from the run, so pcscd is never poked at app startup."""
    fake_backend.patch(doctor_view, "run_doctor", _ok_result())
    fake_backend.patch(doctor_view, "list_readers",
                       backend.Result(True, ["ACS ACR38U-CCID 00 00", "Otro 01 00"]))

    view = make_view(doctor_view.DoctorView)
    assert [view._reader.itemText(i) for i in range(view._reader.count())] == ["Automático"]

    with qtbot.waitSignal(view._readers.finished, timeout=5000):
        view._on_check()

    assert [view._reader.itemText(i) for i in range(view._reader.count())] == [
        "Automático", "ACS ACR38U-CCID 00 00", "Otro 01 00",
    ]


def test_a_chosen_reader_survives_the_list_being_refreshed(make_view, qtbot, fake_backend):
    fake_backend.patch(doctor_view, "run_doctor", _ok_result())
    fake_backend.patch(doctor_view, "list_readers", backend.Result(True, ["A", "B"]))

    view = make_view(doctor_view.DoctorView)
    with qtbot.waitSignal(view._readers.finished, timeout=5000):
        view._on_check()
    view._reader.setCurrentIndex(view._reader.findData("B"))

    with qtbot.waitSignal(view._readers.finished, timeout=5000):
        view._on_check()

    assert view._reader.currentData() == "B"


def test_the_chosen_reader_and_backend_reach_the_call(make_view, qtbot, fake_backend):
    fake_backend.patch(doctor_view, "run_doctor", _ok_result())
    fake_backend.patch(doctor_view, "list_readers", backend.Result(True, ["A"]))

    view = make_view(doctor_view.DoctorView)
    with qtbot.waitSignal(view._readers.finished, timeout=5000):
        view._on_check()

    view._reader.setCurrentIndex(view._reader.findData("A"))
    view._pkcs11.setChecked(True)
    with qtbot.waitSignal(view._doctor.finished, timeout=5000):
        view._on_check()

    kwargs = fake_backend.kwargs_for("run_doctor")
    assert kwargs["reader"] == "A"
    assert kwargs["native"] is False


def test_diagnosing_the_other_backend_does_not_change_the_setting(make_view, qtbot, fake_backend):
    """The radios are a diagnostic override. Ajustes still decides what signing uses."""
    settings.save(settings.Settings(native=True))
    fake_backend.patch(doctor_view, "run_doctor", _ok_result())
    fake_backend.patch(doctor_view, "list_readers", backend.Result(True, []))

    view = make_view(doctor_view.DoctorView)
    view._pkcs11.setChecked(True)
    with qtbot.waitSignal(view._doctor.finished, timeout=5000):
        view._on_check()

    assert settings.load().native is True


def test_refreshing_the_cas_logs_progress_and_the_destination(make_view, qtbot, fake_backend):
    def fake(*, progress):
        progress("bajando la raíz")
        progress("bajando la intermedia")
        return backend.Result(True, backend.CaPaths("/c/acrn.cer", "/c/mica.cer", "/c"))

    fake_backend.patch(doctor_view, "refresh_cas", side_effect=fake)

    view = make_view(doctor_view.DoctorView)
    assert view._cas_log.isHidden() is True

    with qtbot.waitSignal(view._cas.finished, timeout=5000):
        view._on_refresh_cas()

    log = view._cas_log.toPlainText()
    assert "bajando la raíz" in log
    assert "bajando la intermedia" in log
    assert "/c" in log
    assert view._cas_btn.isEnabled() is True


def test_a_failed_ca_download_says_why(make_view, qtbot, fake_backend):
    fake_backend.patch(doctor_view, "refresh_cas",
                       backend.Result(False, None, "fingerprint mismatch", "other"))

    view = make_view(doctor_view.DoctorView)
    with qtbot.waitSignal(view._cas.finished, timeout=5000):
        view._on_refresh_cas()

    assert "fingerprint mismatch" in view._cas_log.toPlainText()
    assert view._cas_btn.isEnabled() is True


def test_a_truncated_check_list_renders_fine(make_view, qtbot, fake_backend):
    """firmauy's native and PKCS#11 branches return early on a failing check, so the list can be
    much shorter than usual. Nothing here may assume a fixed number of rows."""
    fake_backend.patch(doctor_view, "run_doctor", backend.DoctorResult(False, [
        _check("WARN", "PC/SC reader detected", "none found", "Conectá un lector."),
    ]))
    fake_backend.patch(doctor_view, "list_readers", backend.Result(True, []))

    view = make_view(doctor_view.DoctorView)
    with qtbot.waitSignal(view._doctor.finished, timeout=5000):
        view._on_check()

    assert "Hay algo para revisar" in widget_text(view._status)
    assert view._status.property("tone") == "bad"
    assert "Conectá un lector." in widget_text(view._checks)


def test_the_reader_and_the_backend_are_frozen_for_the_whole_chain(make_view, qtbot,
                                                                   fake_backend, monkeypatch):
    """Both are read once, when run_doctor starts, and the reader list runs chained after it.

    Left live, a result arrives under controls that already show a different setup, so the screen
    answers about one configuration while describing another. Held open by a blocked worker, so
    the claim is made while it is supposed to be true rather than after everything settled.
    """
    import threading

    running, release = threading.Event(), threading.Event()

    def blocked(**kw):
        running.set()
        release.wait(5)
        return backend.DoctorResult(True, [_check()])

    monkeypatch.setattr(doctor_view, "run_doctor", blocked)
    fake_backend.patch(doctor_view, "list_readers", backend.Result(True, []))

    view = make_view(doctor_view.DoctorView)
    assert view._what_to_check.isEnabled() is True

    with qtbot.waitSignal(view._readers.finished, timeout=5000):
        view._on_check()
        assert running.wait(2), "the worker never started"
        assert view._what_to_check.isEnabled() is False
        assert view._button.isEnabled() is False
        release.set()

    assert view._what_to_check.isEnabled() is True      # handed back when the chain ends
    assert view._button.isEnabled() is True


def test_a_failed_diagnosis_hands_the_controls_back(make_view, qtbot, fake_backend):
    """The error path releases the card and never reaches the chained reader list, so it has to
    unfreeze on its own or the screen stays locked."""
    fake_backend.patch(doctor_view, "run_doctor",
                       backend.DoctorResult(False, [], error="algo se rompió"))

    view = make_view(doctor_view.DoctorView)
    with qtbot.waitSignal(view._doctor.finished, timeout=5000):
        view._on_check()

    assert view._what_to_check.isEnabled() is True
    assert view._card.busy is False


def test_the_button_stays_down_until_the_chained_call_comes_back(make_view, qtbot,
                                                                 fake_backend, monkeypatch):
    """The card lock covers the checks and the reader list together and is released when the
    second one returns. _on_checked used to re-enable the button before that, so pressing it
    answered "la cédula está ocupada": the panel was frozen for the pair and the button was not.
    """
    import threading

    running, release = threading.Event(), threading.Event()

    def blocked():
        running.set()
        release.wait(5)
        return backend.Result(True, [])

    fake_backend.patch(doctor_view, "run_doctor", _ok_result())
    monkeypatch.setattr(doctor_view, "list_readers", blocked)

    view = make_view(doctor_view.DoctorView)
    with qtbot.waitSignal(view._readers.finished, timeout=5000):
        view._on_check()
        # waitUntil, not Event.wait: this second call only starts once the first one's finished
        # signal is delivered, and blocking the main thread stops the loop that delivers it.
        qtbot.waitUntil(running.is_set, timeout=3000)
        # The checks are done. The card is not free yet.
        assert view._card.busy is True
        assert view._button.isEnabled() is False
        release.set()

    assert view._card.busy is False
    assert view._button.isEnabled() is True


# --- the repair, folded until it is needed ------------------------------------

def test_a_healthy_diagnosis_leaves_the_repair_folded(make_view, qtbot, fake_backend):
    """The section used to be an always-open group box, so "Todo en orden" sat above a
    paragraph, a button and room for a log about a problem nobody had."""
    fake_backend.patch(doctor_view, "run_doctor", _ok_result())
    fake_backend.patch(doctor_view, "list_readers", backend.Result(True, []))

    view = make_view(doctor_view.DoctorView)
    assert view._cas_box.is_expanded() is False

    with qtbot.waitSignal(view._readers.finished, timeout=5000):
        view._on_check()

    assert view._cas_box.is_expanded() is False
    # Folded is not gone: the button is still there for whoever unfolds it.
    assert view._cas_btn.isHidden() is False


def test_a_diagnosis_with_findings_unfolds_the_repair(make_view, qtbot, fake_backend):
    """Opened on "anything needs looking at" rather than on a CA check by name, because nothing
    in this app is allowed to switch on a check's name: firmauy is free to rename or add them,
    and every name lookup degrades silently the day it does."""
    fake_backend.patch(doctor_view, "run_doctor", backend.DoctorResult(False, [
        _check(status="FAIL", name="bundled national CA certificates", detail="missing"),
    ]))
    fake_backend.patch(doctor_view, "list_readers", backend.Result(True, []))

    view = make_view(doctor_view.DoctorView)
    with qtbot.waitSignal(view._readers.finished, timeout=5000):
        view._on_check()

    assert view._cas_box.is_expanded() is True


def test_a_person_who_unfolded_the_repair_keeps_it_through_a_healthy_run(make_view, qtbot,
                                                                         fake_backend):
    """Opening happens on the app's initiative and closing never does. Folding a section the
    person deliberately opened would be the app arguing with them about their own window."""
    fake_backend.patch(doctor_view, "run_doctor", _ok_result())
    fake_backend.patch(doctor_view, "list_readers", backend.Result(True, []))

    view = make_view(doctor_view.DoctorView)
    view._cas_box.set_expanded(True)

    with qtbot.waitSignal(view._readers.finished, timeout=5000):
        view._on_check()

    assert view._cas_box.is_expanded() is True
