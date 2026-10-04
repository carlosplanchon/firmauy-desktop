# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the Verificar screen.

Everything this screen shows comes out of a certificate inside a file somebody else sent the
user. That used to make escaping the test that mattered most; now the labels are plain text and
the claim is stronger and simpler: the value arrives exactly as the certificate spells it.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from conftest import widget_text
from firmauy_desktop import backend, settings
from firmauy_desktop.views import verify_view

# What an attacker would put in a certificate's common name. Against a RichText label the img tag
# made QTextDocument resolve a local resource and the bare < swallowed the rest of the line; a
# PlainText label has nothing to do with either, which is the point.
_HOSTILE = '<img src="file:///etc/passwd">JUAN <PEREZ'


def _signature(indication="VALID", signer="PEREZ PEREZ JUAN", trusted=True):
    return backend.Signature(
        indication=indication,
        trusted=trusted,
        signer=backend.Party(signer, "DNI12345672", "", "UY", "0A1B2C"),
        issuer=backend.Party("Autoridad Certificadora del Ministerio del Interior"),
        checks=[
            backend.Check("signature cryptographically valid", True),
            # "not trusted" is what firmauy really sends. The fixture used to invent
            # "no path to a trusted root", a string it has never emitted.
            backend.Check("certificate chain to trusted root", trusted,
                          "" if trusted else "not trusted"),
        ],
    )


def _report(indication="VALID", **kw):
    return backend.VerifyResult(indication, [_signature(indication=indication, **kw)])


def _verify(qtbot, view, path="/tmp/firmado.pdf"):
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view.load(path)


def test_a_hostile_signer_name_comes_out_inert(make_view, qtbot, fake_backend):
    """Everything on this screen comes out of a certificate in a file somebody else sent.

    The claim is stronger than the escaped version it replaces: the name arrives **intact**,
    not mangled into entities, because a plain text label has nothing to interpret. There is no
    markup to neutralise, so there is nothing left to get wrong.
    """
    fake_backend.patch(verify_view, "verify_file", _report(signer=_HOSTILE))

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)

    assert _HOSTILE in widget_text(view._signers)
    assert all(lbl.textFormat() == Qt.TextFormat.PlainText
               for lbl in view._signers.findChildren(QLabel))


def test_the_verdict_says_what_it_means_in_plain_spanish(make_view, qtbot, fake_backend):
    fake_backend.patch(verify_view, "verify_file", _report("INDETERMINATE", trusted=False))

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)

    assert "INDETERMINADO" in widget_text(view._verdict)
    assert "No se puede afirmar que sea válida" in widget_text(view._verdict)
    assert view._verdict._word.property("tone") == "warn"


def test_the_signer_card_shows_the_fields_the_old_screen_threw_away(make_view, qtbot, fake_backend):
    fake_backend.patch(verify_view, "verify_file", _report())

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)

    signers = widget_text(view._signers)
    assert "PEREZ PEREZ JUAN" in signers
    assert "DNI12345672" in signers                      # the signer's cédula, per the cert
    assert "Ministerio del Interior" in signers
    assert "llega a la raíz nacional" in signers         # `trusted`, which used to be discarded


def test_an_untrusted_chain_is_said_so(make_view, qtbot, fake_backend):
    fake_backend.patch(verify_view, "verify_file", _report("INDETERMINATE", trusted=False))

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)

    assert "no llega a la raíz nacional" in widget_text(view._signers)


def test_the_technical_details_carry_each_check_and_its_detail(make_view, qtbot, fake_backend):
    fake_backend.patch(verify_view, "verify_file", _report("INDETERMINATE", trusted=False))

    view = make_view(verify_view.VerifyView)
    assert view._details_box.isHidden() is True

    _verify(qtbot, view)

    assert view._details_box.isHidden() is False
    assert view._details_box.is_expanded() is False      # the answer first, the evidence below
    details = widget_text(view._details)
    assert "La firma es criptográficamente válida" in details
    # The detail, which used to be discarded entirely, and which is glossed like the name: an
    # English sentence in the middle of a Spanish screen was the last thing reading as a tool log.
    assert "no es de confianza" in details
    assert "0A1B2C" in details                           # the certificate serial


def test_an_unknown_check_name_renders_instead_of_disappearing(make_view, qtbot, fake_backend):
    """firmauy is free to add checks, and the set already differs per format. Nothing here may
    switch on the name."""
    sig = _signature()
    sig.checks.append(backend.Check("some future check", True, "algo"))
    fake_backend.patch(verify_view, "verify_file", backend.VerifyResult("VALID", [sig]))

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)

    assert "some future check" in widget_text(view._details)


def test_a_detached_p7s_without_its_original_offers_the_picker(make_view, qtbot, fake_backend):
    """The most common verification failure, and the only one the person can fix: the signature
    and the document routinely travel separately by email."""
    fake_backend.patch(verify_view, "verify_file", backend.VerifyResult(
        "", error="Este .p7s está separado del archivo que firmó. Se buscó contrato.pdf al lado "
                  "y no está. ¿Cuál es?",
        error_kind="needs_original"))

    view = make_view(verify_view.VerifyView)
    assert view._original_row.isHidden() is True

    _verify(qtbot, view, "/tmp/contrato.pdf.p7s")

    assert view._original_row.isHidden() is False
    assert "contrato.pdf" in view._original_label.text()


def test_choosing_the_original_re_verifies_with_it(make_view, qtbot, fake_backend, monkeypatch):
    fake_backend.patch(verify_view, "verify_file", backend.VerifyResult(
        "", error="falta el original", error_kind="needs_original"))

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view, "/tmp/contrato.pdf.p7s")

    fake_backend.patch(verify_view, "verify_file", _report())
    monkeypatch.setattr(verify_view.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("/tmp/contrato.pdf", "")))

    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._pick_original()

    assert fake_backend.kwargs_for("verify_file")["original"] == "/tmp/contrato.pdf"
    assert view._original_row.isHidden() is True
    assert "VÁLIDO" in widget_text(view._verdict)


def test_a_plain_error_does_not_offer_the_picker(make_view, qtbot, fake_backend):
    fake_backend.patch(verify_view, "verify_file",
                       backend.VerifyResult("", error="no se pudo leer el archivo",
                                            error_kind="other"))

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)

    assert view._verdict.isHidden() is True
    assert "no se pudo leer el archivo" in widget_text(view._status)
    assert view._status.property("tone") == "bad"
    assert view._original_row.isHidden() is True


# --- revocation, the only network I/O here ----------------------------------

def test_revocation_is_off_by_default_and_reaches_the_call(make_view, qtbot, fake_backend):
    fake_backend.patch(verify_view, "verify_file", _report())

    view = make_view(verify_view.VerifyView)
    assert view._revocation.isChecked() is False

    _verify(qtbot, view)
    assert fake_backend.kwargs_for("verify_file")["check_revocation"] is False

    view._revocation.setChecked(True)
    _verify(qtbot, view)
    assert fake_backend.kwargs_for("verify_file")["check_revocation"] is True


def test_the_local_network_reaches_the_call_only_when_ajustes_says_so(make_view, qtbot,
                                                                      fake_backend):
    """The revocation lookups follow addresses out of the certificates in the file, so whether
    they may reach a private one is Ajustes' decision, read at the start of each verification."""
    fake_backend.patch(verify_view, "verify_file", _report())
    view = make_view(verify_view.VerifyView)

    _verify(qtbot, view)
    assert fake_backend.kwargs_for("verify_file")["allow_private_network"] is False

    settings.save(settings.Settings(allow_private_network=True))
    _verify(qtbot, view)
    assert fake_backend.kwargs_for("verify_file")["allow_private_network"] is True


def test_toggling_revocation_persists_it(make_view, qtbot, fake_backend):
    """So this checkbox and the one in Ajustes never disagree."""
    view = make_view(verify_view.VerifyView)

    view._revocation.setChecked(True)
    assert settings.load().check_revocation is True

    view._revocation.setChecked(False)
    assert settings.load().check_revocation is False


def test_the_stop_button_only_appears_when_a_hang_is_possible(make_view, qtbot, fake_backend):
    """A QThread parked in an OCSP fetch cannot be killed, so this stops waiting rather than
    cancelling, and it is pointless when the verification is offline."""
    import threading

    release = threading.Event()

    def slow(path, **kw):
        release.wait(5)
        return _report()

    fake_backend.patch(verify_view, "verify_file", side_effect=slow)

    view = make_view(verify_view.VerifyView)

    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view.load("/tmp/firmado.pdf")                    # offline: no way to hang
        assert view._stop_btn.isHidden() is True
        release.set()

    release.clear()
    view._revocation.setChecked(True)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view.load("/tmp/firmado.pdf")
        assert view._stop_btn.isHidden() is False
        release.set()

    assert view._stop_btn.isHidden() is True             # gone once it settled


def test_stopping_frees_the_screen_and_says_what_to_try(make_view, qtbot, fake_backend):
    import threading

    release = threading.Event()
    fake_backend.patch(verify_view, "verify_file",
                       side_effect=lambda path, **kw: release.wait(5) and _report())

    view = make_view(verify_view.VerifyView)
    view._revocation.setChecked(True)
    view.load("/tmp/firmado.pdf")

    view._on_stop()
    assert view._runner.busy is False                    # ready for the next file right away
    assert view._drop.isEnabled() is True
    assert "sin marcarla" in widget_text(view._status)

    release.set()
    view.shutdown()


# --- what a running verification owns ----------------------------------------

def test_a_second_file_cannot_be_taken_while_one_is_being_verified(make_view, qtbot,
                                                                   fake_backend, monkeypatch):
    """The worst thing a verifier can do, and it did it.

    The drop area is disabled during a run, but the Archivo menu and Firmar's "Verificar el
    archivo firmado" both call load() and neither was blocked. `_path` became the new file, the
    runner declined to start, and the previous file's verdict landed on a screen that now
    believed it was about this one. Nothing on the screen names the file, so there was nothing
    to notice.
    """
    import threading

    started = threading.Event()
    asked = []

    def slow(path, **kw):
        asked.append(path)
        started.set()
        return backend.VerifyResult("VALID", [_signature()])

    fake_backend.patch(verify_view, "verify_file", None)
    monkeypatch.setattr(verify_view, "verify_file", slow)

    view = make_view(verify_view.VerifyView)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view.load("/tmp/A.pdf")
        view.load("/tmp/B.pdf")          # as the menu would, mid-run

    assert asked == ["/tmp/A.pdf"]
    assert view._path == "/tmp/A.pdf"    # the screen still knows what it answered about


def test_revocation_cannot_be_changed_under_a_running_check(make_view, qtbot, monkeypatch):
    """It is read once, when the task starts. Leaving it live only lets the screen contradict
    the answer it is about to give.

    Held open by a blocked worker on purpose. The first version of this test asserted only that
    the checkbox came back enabled at the end, which is true whether or not it is ever disabled:
    it would have passed with the freeze deleted.
    """
    import threading

    running, release = threading.Event(), threading.Event()

    def blocked(path, **kw):
        running.set()
        release.wait(5)
        return backend.VerifyResult("VALID", [_signature()])

    monkeypatch.setattr(verify_view, "verify_file", blocked)

    view = make_view(verify_view.VerifyView)
    assert view._revocation.isEnabled() is True
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view.load("/tmp/firmado.pdf")
        assert running.wait(2), "the worker never started"
        assert view._revocation.isEnabled() is False        # the claim, made while it is true
        assert view._drop.isEnabled() is False
        release.set()

    assert view._revocation.isEnabled() is True             # and handed back when it settles


# --- what the verdict does not cover -----------------------------------------

def test_a_valid_verdict_says_revocation_was_not_consulted(make_view, qtbot, fake_backend):
    """With revocation off firmauy runs no revocation check, so there is no row for it anywhere.

    A check that was not run has no result, and its absence is invisible among four green ticks.
    VÁLIDO then quietly means "intact and correctly signed", which is not the same as "still
    good", and the word is the part a person remembers.
    """
    fake_backend.patch(verify_view, "verify_file", _report())

    view = make_view(verify_view.VerifyView)
    view._revocation.setChecked(False)
    _verify(qtbot, view)

    assert view._scope.isHidden() is False
    assert "no consultada" in widget_text(view._scope)
    # The claim carries body weight. It used to be one muted caption under the largest word in
    # the app, which made the boundary of what VÁLIDO means the easiest thing on the screen to
    # skip, and that boundary is close to being part of the security model.
    assert view._scope_head.property("role") == "body"
    # The explanation under it stays quiet, and neither half is painted as a failure: off is
    # the default and the ordinary case is not a warning.
    assert view._scope_detail.property("tone") == "muted"
    assert view._scope_head.property("tone") not in ("warn", "bad")


def test_a_consulted_revocation_on_a_valid_file_says_what_came_of_it(make_view, qtbot,
                                                                     fake_backend):
    """Asked plus VÁLIDO licenses the stronger sentence: firmauy would not have called it valid
    over a revoked certificate."""
    fake_backend.patch(verify_view, "verify_file", _report())

    view = make_view(verify_view.VerifyView)
    view._revocation.setChecked(True)
    _verify(qtbot, view)

    assert "No constaba revocado" in widget_text(view._scope)


@pytest.mark.parametrize("indication", ["INVALID", "INDETERMINATE"])
def test_a_consulted_revocation_on_a_bad_result_claims_nothing(make_view, qtbot, fake_backend,
                                                               indication):
    """"Revocación consultada" beside an INVÁLIDO is true and useless: it says the question was
    asked without saying what came of it, and next to a bad verdict a person reads it as the
    reason for the verdict."""
    fake_backend.patch(verify_view, "verify_file", _report(indication, trusted=False))

    view = make_view(verify_view.VerifyView)
    view._revocation.setChecked(True)
    _verify(qtbot, view)

    scope = widget_text(view._scope)
    # "solicitada", not "consultada": asking is all the app knows it did.
    assert "Revocación: solicitada" in scope
    assert "no confirma el estado" in scope
    assert "No constaba revocado" not in scope
    assert "consultada" not in scope


def test_the_scope_describes_the_run_that_produced_the_answer(make_view, qtbot, fake_backend):
    """Read from what the task was started with, not from the checkbox afterwards. The checkbox
    is frozen during a run, not removed, and the answer belongs to the value it had at the
    start."""
    fake_backend.patch(verify_view, "verify_file", _report())

    view = make_view(verify_view.VerifyView)
    view._revocation.setChecked(True)
    _verify(qtbot, view)
    view._revocation.setChecked(False)          # changed after the answer arrived

    assert "No constaba revocado" in widget_text(view._scope)


def test_the_scope_goes_away_while_a_new_check_runs(make_view, qtbot, fake_backend,
                                                    monkeypatch):
    """It describes an answer. There is none while one is being worked out, and a line about the
    previous file's scope sitting over a running check is the stale-context problem again."""
    import threading

    running, release = threading.Event(), threading.Event()

    def blocked(path, **kw):
        running.set()
        release.wait(5)
        return backend.VerifyResult("VALID", [_signature()])

    fake_backend.patch(verify_view, "verify_file", _report())
    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)
    assert view._scope.isHidden() is False

    monkeypatch.setattr(verify_view, "verify_file", blocked)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view.load("/tmp/otro.pdf")
        qtbot.waitUntil(running.is_set, timeout=3000)
        assert view._scope.isHidden() is True
        release.set()


def test_an_unsigned_pdf_is_not_told_its_revocation_was_consulted(make_view, qtbot, monkeypatch,
                                                                  tmp_path):
    """The case the wording turns on, run through the real verifier rather than a fake one.

    Verification needs no card and no network unless revocation is on, so this can exercise
    firmauy for real. A valid PDF with no signature in it comes back INVALID after a single
    check, and no revocation lookup happens at all: there is no certificate to look one up for.
    Saying it was consulted would describe something that did not occur, which is why the
    sentence says only that it was asked for.
    """
    from reportlab.pdfgen import canvas

    from firmauy_desktop import backend

    path = tmp_path / "sin-firma.pdf"
    page = canvas.Canvas(str(path))
    page.drawString(100, 750, "documento sin firmar")
    page.save()

    # The guard replaces this with a refusal. Verifying touches no card, so the real one is put
    # back deliberately and visibly rather than by accident.
    monkeypatch.setattr(verify_view, "verify_file", backend.verify_file)

    view = make_view(verify_view.VerifyView)
    view._revocation.setChecked(True)
    _verify(qtbot, view, str(path))

    assert "INVÁLIDO" in widget_text(view._verdict)
    scope = widget_text(view._scope)
    assert "Revocación: solicitada" in scope
    assert "Revocación: consultada" not in scope


# --- the timestamp ----------------------------------------------------------

def _stamped(*, sound=True, trusted=None, tsa="Sellado de Tiempo Ejemplo CA",
             indication="VALID"):
    from datetime import datetime, timezone

    sig = _signature(indication=indication)
    sig.timestamp = backend.Timestamp(
        present=True, intact=sound, valid=sound, trusted=trusted,
        gen_time=datetime(2026, 7, 30, 14, 32, 11, tzinfo=timezone.utc),
        tsa=tsa,
        detail="timestamp token signature is invalid" if not sound else "genTime 2026-07-30 (trusted)",
    )
    return backend.VerifyResult(indication, [sig])


def test_a_stamped_file_says_when_it_was_signed(make_view, qtbot, fake_backend):
    """One of the two questions somebody opens this screen with. Until firmauy 1.12.0 a PDF's
    timestamp was discarded before it ever reached here, so the answer was simply absent."""
    fake_backend.patch(verify_view, "verify_file", _stamped())

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)

    signers = widget_text(view._signers)
    assert "Sello de tiempo" in signers
    assert "30/07/2026" in signers


def test_the_date_is_attributed_rather_than_vouched_for(make_view, qtbot, fake_backend):
    """This app supplies no TSA anchors, so no stamp it reports has had its chain evaluated.
    Saying the date plainly would be claiming somebody checked."""
    fake_backend.patch(verify_view, "verify_file", _stamped(trusted=None))

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)

    assert "según la TSA" in widget_text(view._signers)


def test_the_provider_is_named(make_view, qtbot, fake_backend):
    """Who issued the stamp is exactly what decides whether Ley 18.600 is satisfied, so it is
    not a technical aside."""
    fake_backend.patch(verify_view, "verify_file", _stamped(tsa="Sellado de Tiempo Ejemplo CA"))

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)

    assert "Sellado de Tiempo Ejemplo CA" in widget_text(view._signers)


def test_a_file_without_a_stamp_says_so_rather_than_staying_quiet(make_view, qtbot,
                                                                  fake_backend):
    """An absent row is not an answer: nobody notices a row that is not there. VÁLIDO on an
    unstamped file quietly means "intact and correctly signed, at no particular date"."""
    fake_backend.patch(verify_view, "verify_file", _report())

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)

    assert "no lleva sello de tiempo" in widget_text(view._signers)


def test_an_unstamped_file_is_not_dressed_up_as_a_problem(make_view, qtbot, fake_backend):
    """Most signed files carry no stamp. A red cross there would read as a defect in a document
    that has none, and the law paragraph would be advice about a decision nobody made."""
    fake_backend.patch(verify_view, "verify_file", _report())

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)

    assert verify_view._timestamp_mark(None) is None
    assert "18.600" not in widget_text(view._signers)


def test_a_stamped_file_carries_the_law(make_view, qtbot, fake_backend):
    """The same point Ajustes makes beside the TSA field, from the other end: there somebody is
    choosing a provider, here somebody is reading a date another party's provider put in a file,
    and the second is where believing too much actually costs something."""
    fake_backend.patch(verify_view, "verify_file", _stamped())

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)

    signers = widget_text(view._signers)
    assert "18.600" in signers
    assert "UCE" in signers


def test_a_broken_stamp_is_marked_and_explained(make_view, qtbot, fake_backend):
    fake_backend.patch(verify_view, "verify_file",
                       _stamped(sound=False, indication="INDETERMINATE"))

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)

    assert "la firma del sello de tiempo no es válida" in widget_text(view._signers)
    assert verify_view._timestamp_mark(_stamped(sound=False).signatures[0].timestamp) is False


def test_a_broken_stamp_does_not_contradict_the_word_above_it(make_view, qtbot, fake_backend):
    """firmauy 1.12.0 stopped calling this VALID, and the screen has to agree. A green VÁLIDO
    over a red row admitting the token is broken is the mixed message the whole change removes,
    and the word is the part somebody remembers."""
    fake_backend.patch(verify_view, "verify_file",
                       _stamped(sound=False, indication="INDETERMINATE"))

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)

    verdict = widget_text(view._verdict)
    assert "INDETERMINADO" in verdict
    assert "VÁLIDO" not in verdict
    # And the sentence under it names this as one of the things that can be wrong, instead of
    # sending somebody to look at their trust anchors for a problem that is in the file.
    assert "sello de tiempo" in verdict


def test_a_sound_stamp_is_ticked_and_a_chain_that_failed_is_not():
    from datetime import datetime, timezone

    when = datetime(2026, 7, 30, tzinfo=timezone.utc)
    sound = backend.Timestamp(present=True, intact=True, valid=True, gen_time=when)

    assert verify_view._timestamp_mark(sound) is True
    # trusted=False is a chain that was evaluated and did not reach a root, which this app cannot
    # produce today (it passes no anchors) but firmauy can report.
    sound.trusted = False
    assert verify_view._timestamp_mark(sound) is False


def test_the_stamp_survives_a_second_verification(make_view, qtbot, fake_backend):
    """The signer card is rebuilt per run, and a stale law paragraph under an unstamped file
    would be the same orphan bug clear_layout exists for."""
    fake_backend.patch(verify_view, "verify_file", _stamped())
    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)
    assert "18.600" in widget_text(view._signers)

    fake_backend.patch(verify_view, "verify_file", _report())
    _verify(qtbot, view)

    signers = widget_text(view._signers)
    assert "18.600" not in signers
    assert "no lleva sello de tiempo" in signers


# --- judging who issued the stamp ---------------------------------------------

def test_the_tsa_box_is_off_until_somebody_ticks_it(make_view, qtbot):
    """Off is the honest default. The anchors are on the machine either way, so this is not about
    cost: turning it on is a statement that the bundled roots are accepted as timestamping
    authorities, and the app has not been told that."""
    view = make_view(verify_view.VerifyView)

    assert view._validate_tsa.isChecked() is False


def test_ticking_it_sends_anchors_and_leaving_it_does_not(make_view, qtbot, fake_backend, monkeypatch):
    seen = []

    def spy(path, **kw):
        seen.append(kw.get("tsa_ca"))
        return _stamped()

    monkeypatch.setattr(verify_view, "verify_file", spy)
    view = make_view(verify_view.VerifyView)

    _verify(qtbot, view)
    view._validate_tsa.setChecked(True)
    _verify(qtbot, view)

    assert seen[0] is None, "anchors travelled without being asked for"
    assert seen[1], "the box was ticked and no anchors travelled"


def test_the_box_survives_a_restart(make_view, qtbot, fake_backend):
    """Persisted like the revocation box beside it, so the screen and Ajustes never disagree."""
    view = make_view(verify_view.VerifyView)
    view._validate_tsa.setChecked(True)

    assert settings.load().validate_tsa is True

    again = make_view(verify_view.VerifyView)
    assert again._validate_tsa.isChecked() is True


def test_both_boxes_come_back_after_a_verification(make_view, qtbot, fake_backend):
    """They are frozen for the duration, because toggling either mid-run cannot change the answer
    that is coming. Settling them again is the half that would strand somebody if it were missed.
    """
    fake_backend.patch(verify_view, "verify_file", _report())
    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)

    assert view._validate_tsa.isEnabled() is True
    assert view._revocation.isEnabled() is True


def test_the_answer_sits_above_the_file_that_produced_it(make_view, qtbot):
    """The verdict used to be the fourth thing down, under a large dashed box and two technical
    checkboxes, so opening a signed document read as filling in a form that also answered you.
    Asserted by position rather than by eye, because a widget can be moved back by accident."""
    view = make_view(verify_view.VerifyView)
    order = [view.body.indexOf(w) for w in
             (view._verdict, view._drop, view._options, view._signers)]

    assert order == sorted(order), "the answer is not first"
    assert view.body.indexOf(view._verdict) < view.body.indexOf(view._drop)
    assert view.body.indexOf(view._drop) < view.body.indexOf(view._options)


def test_the_big_drop_area_gives_way_once_there_is_a_file(make_view, qtbot):
    """It is the right shape while it is the only thing to do, and the wrong one afterwards: the
    heaviest element on screen spent on the step already finished, above the answer."""
    view = make_view(verify_view.VerifyView)

    assert view._drop.isHidden() is False
    assert view._chosen.isHidden() is True

    view._path = "/home/ana/contrato.pdf.p7s"
    view._refresh_input()

    assert view._drop.isHidden() is True
    assert view._chosen.isHidden() is False
    assert "contrato.pdf.p7s" in widget_text(view._chosen)
    assert "/home/ana" in widget_text(view._chosen), "two files of the same name need the folder"


def test_the_options_are_folded_away_and_still_work(make_view, qtbot):
    """They decide how much is checked, which is a question about the verification and not about
    the document. Folded, not removed: the checkboxes keep their state and their signals."""
    view = make_view(verify_view.VerifyView)

    assert view._options.isHidden() is False
    assert view._revocation.isVisibleTo(view._options) is False, "not folded away"

    view._options.set_expanded(True)
    assert view._revocation.isVisibleTo(view._options) is True
    assert view._validate_tsa.isVisibleTo(view._options) is True


def test_choosing_another_file_is_frozen_while_one_is_verifying(make_view, qtbot,
                                                                fake_backend, monkeypatch):
    """The compact row carries the only way to change the file once the big area is gone, so it
    has to freeze with everything else. A second file accepted mid-run is the failure `load`
    already guards against."""
    view = make_view(verify_view.VerifyView)
    view._path = "/home/ana/contrato.pdf.p7s"
    view._refresh_input()

    view._another_btn.setEnabled(False)          # what _start does
    assert view._another_btn.isEnabled() is False
    view._settle()
    assert view._another_btn.isEnabled() is True


# --- the pointer to the State validator --------------------------------------

def test_a_verdict_arrives_with_the_pointer_to_the_state_validator(make_view, qtbot,
                                                                   fake_backend):
    """The arbiter a counterparty will use is firma.gub.uy, and the person this screen is for
    never reads the README that says so. With the verdict rather than permanent: before there
    is an answer there is nothing to cross-check, and a notice that is always there is the one
    the eye learns to skip. The privacy cost is a stated fact, not advice: the sentence says
    the document is sent, and what to do about that is the person's own call."""
    fake_backend.patch(verify_view, "verify_file", _report())

    view = make_view(verify_view.VerifyView)
    assert view._crosscheck.isHidden() is True

    _verify(qtbot, view)

    assert view._crosscheck.isHidden() is False
    advice = widget_text(view._crosscheck)
    assert "firma.gub.uy" in advice
    assert "envía el documento" in advice


def test_the_validator_button_opens_the_site_and_nothing_else(make_view, qtbot, fake_backend,
                                                              monkeypatch):
    """A browser launch on request, never an upload: the app itself sends nothing anywhere."""
    fake_backend.patch(verify_view, "verify_file", _report())

    opened = []

    class _Browser:
        @staticmethod
        def openUrl(url):
            opened.append(url.toString())
            return True

    from firmauy_desktop import widgets

    monkeypatch.setattr(widgets, "QDesktopServices", _Browser)

    view = make_view(verify_view.VerifyView)
    _verify(qtbot, view)
    view._validator_btn.click()

    assert opened == ["https://firma.gub.uy/"]
