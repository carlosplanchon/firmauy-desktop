# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the error translation.

Pure functions, no Qt and no monkeypatching. Two jobs: check that every failure a person can
run into gets a sentence they can act on, and pin the Spanish so an edit has to be deliberate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from firmauy.api import (
    CardNotFoundError,
    CertificateNotFoundError,
    CertificateNotValidError,
    DetachedOriginalRequiredError,
    FirmaUYError,
    IncorrectPinError,
    OutputExistsError,
    PinError,
    PinFormatError,
    PinLastTryError,
    PinLockedError,
    ReaderNotFoundError,
    SigningKeyNotFoundError,
    TimestampDestinationRefusedError,
    TimestampError,
    TokenNotFoundError,
)

from firmauy_desktop import backend

_NEEDS_ORIGINAL = DetachedOriginalRequiredError(
    "detached .p7s needs its original file (pass original=...)",
    p7s_path=Path("/tmp/contrato.pdf.p7s"), expected=Path("/tmp/contrato.pdf"),
)


@pytest.mark.parametrize("exc, kind, fragment", [
    (IncorrectPinError("x", attempts_remaining=2), "pin", "Te quedan 2 intentos"),
    (IncorrectPinError("x", attempts_remaining=1), "pin", "Te queda 1 intento"),
    (IncorrectPinError("x"), "pin", "PIN incorrecto."),
    (PinLockedError("x"), "pin_locked", "bloqueado"),
    (ReaderNotFoundError("x"), "reader", "lector"),
    (CardNotFoundError("x"), "card", "cédula"),
    (CertificateNotValidError("x"), "cert", "validez"),
    (CertificateNotFoundError("x"), "cert", "certificado de firma"),
    (SigningKeyNotFoundError("x"), "cert", "clave de firma"),
    (TokenNotFoundError("x"), "token", "PKCS#11"),
    (FileNotFoundError("x"), "not_found", "No se encontró el archivo"),
    (PermissionError("x"), "other", "permiso"),
    (_NEEDS_ORIGINAL, "needs_original", "contrato.pdf"),
])
def test_every_failure_gets_a_message_and_a_tag(exc, kind, fragment):
    assert backend._kind(exc) == kind
    assert fragment in backend._translate(exc)


def test_the_singular_warns_that_the_card_is_one_try_from_locking():
    """A wrong PIN spends a card try, and the card blocks at zero. The last one has to read
    differently from "te quedan 2"."""
    assert "antes de que se bloquee" in backend._translate(
        IncorrectPinError("x", attempts_remaining=1))
    assert "antes de que se bloquee" not in backend._translate(
        IncorrectPinError("x", attempts_remaining=2))


def test_pkcs11_cannot_report_a_count():
    """The middleware does not tell us how many tries are left, so the message must not invent
    a number."""
    message = backend._translate(IncorrectPinError("x", attempts_remaining=None))
    assert message == "PIN incorrecto."


def test_the_last_try_is_not_offered_as_one_the_app_will_spend():
    """firmauy refuses to spend a card's last try, so the next signature from here is turned away
    before the PIN. "Te queda 1 intento" on its own invites exactly that retry, and says nothing
    about the one thing that gets the card signing again."""
    message = backend._translate(IncorrectPinError("x", attempts_remaining=1))

    assert "la app no lo va a usar" in message
    assert "desbloquear la cédula" in message


def test_a_malformed_pin_is_about_its_shape():
    """Letters, or not four to eight digits. Typing it again is the answer, and nothing was spent."""
    exc = PinFormatError("The cédula's PIN is digits only")
    message = backend._translate(exc)

    assert backend._kind(exc) == "pin_format"
    assert "entre 4 y 8 dígitos" in message
    assert "ningún intento" in message


def test_a_card_on_its_last_try_says_to_unblock_it():
    """firmauy will not risk the last try. Telling the person to type the PIN again would be the
    wrong answer: only unblocking the card helps."""
    exc = PinLastTryError("Only 1 PIN try left: aborting for safety.")
    message = backend._translate(exc)

    assert backend._kind(exc) == "pin_last_try"
    assert "desbloquearla" in message
    assert "ningún intento" in message
    assert "dígitos" not in message, "retyping is no answer to a card on its last try"


def test_the_last_try_sentence_holds_when_the_pin_was_already_typed():
    """The direct path counts the tries again right before sending, so this refusal can follow
    the prompt. "La app no lo pidió" would then be false, with the PIN dialog just answered."""
    message = backend._translate(PinLastTryError("Only 1 PIN try left: aborting for safety."))

    assert "no lo pidió" not in message
    assert "no lo usó" in message


def test_a_pin_error_firmauy_has_not_named_yet_is_not_given_a_cause():
    """firmauy raises a subclass every time since 1.20.0. One it adds later is a PIN problem this
    app has no sentence for, and guessing one of the two it knows would tell somebody with a
    typo to unblock their card, or the reverse. The generic answer is the honest one, and it is
    what records the crash that says the app needs a sentence."""
    class SomeNewPinError(PinError):
        pass

    exc = SomeNewPinError("something new")

    assert backend._known(exc) is None
    assert backend._kind(exc) == "card_other"
    assert backend._translate(exc).startswith("Falló de una forma que la app no reconoce")


def test_the_pin_subclasses_keep_their_own_answers():
    """All four are PinErrors. Each has its own answer, and none may fall into another's."""
    assert backend._kind(IncorrectPinError("x", attempts_remaining=2)) == "pin"
    assert backend._kind(PinLockedError("x")) == "pin_locked"
    assert backend._kind(PinFormatError("x")) == "pin_format"
    assert backend._kind(PinLastTryError("x")) == "pin_last_try"


def test_a_tsa_on_the_local_network_names_the_box_that_reaches_it():
    """Before firmauy 1.19 this was pyHanko's OSError: a failure the app did not recognise, in
    English, telling somebody to pass a command-line flag. The answer is a setting, so the
    sentence names it, and names the TSA so somebody can tell which one."""
    exc = TimestampDestinationRefusedError(
        "Refusing to connect to 192.168.1.10: not a public address.",
        host="192.168.1.10", addresses=("192.168.1.10",))
    message = backend._translate(exc)

    assert backend._kind(exc) == "tsa_destination_refused"
    assert "192.168.1.10" in message
    assert "Permitir servidores de la red local" in message
    assert "no se guardó" in message
    assert "--allow-private-network" not in message


def test_a_link_local_tsa_is_not_sent_to_a_box_that_cannot_help():
    """firmauy refuses link-local even with the opt-in on, so suggesting it would be a dead end."""
    exc = TimestampDestinationRefusedError("Refusing to connect to 169.254.169.254.",
                                           host="169.254.169.254", link_local=True)
    message = backend._translate(exc)

    assert backend._kind(exc) == "tsa_destination_refused"
    assert "link-local" in message
    assert "Permitir" not in message, "the opt-in does not reach a link-local address"


def test_any_other_timestamp_failure_says_so_and_keeps_what_firmauy_said():
    """Unreachable, a refusal, a reply that is not a timestamp: one sentence for all of them,
    with firmauy's detail kept, since it is what tells them apart in a report."""
    exc = TimestampError('Timestamp server refused our request: statusString "no", failInfo ""')
    message = backend._translate(exc)

    assert backend._kind(exc) == "tsa_failed"
    assert message.startswith("No se pudo obtener el sello de tiempo")
    assert "refused our request" in message
    assert "no reconoce" not in message


def test_an_existing_output_names_the_file():
    exc = OutputExistsError("exists", path=Path("/tmp/contrato_firmado.pdf"))
    assert "contrato_firmado.pdf" in backend._translate(exc)
    assert backend._kind(exc) == "output_exists"


def test_an_existing_output_without_a_path_still_reads():
    assert "el archivo firmado" in backend._translate(OutputExistsError("exists"))


def test_an_unknown_firmauy_error_is_tagged_as_card_related():
    """Better than "other": it came from the card layer even if we have no wording for it."""
    class Weird(FirmaUYError):
        pass

    assert backend._kind(Weird("algo raro")) == "card_other"
    assert "algo raro" in backend._translate(Weird("algo raro"))


def test_an_error_with_no_wording_is_framed_in_spanish_and_keeps_its_detail():
    """It used to hand over the exception's own text and nothing else, so an untranslated failure
    read as the app switching to English mid-sentence, with no hint that it had run out of things
    to say. The English stays, because it is the only thing a bug report can carry and nothing
    else prints it, but it arrives labelled as a technical string rather than as an answer.
    """
    message = backend._translate(RuntimeError("pcscd is not running"))

    assert message.startswith("Falló de una forma que la app no reconoce")
    assert "pcscd is not running" in message, "the only detail a report could carry was dropped"
    assert backend._kind(RuntimeError("x")) == "other"


def test_an_error_carrying_no_message_still_names_something():
    """str() on an exception built with no arguments is empty, which would end the sentence on a
    colon and tell nobody anything. The class name is at least a thing to search for."""
    assert backend._translate(RuntimeError()).endswith("RuntimeError")
    assert backend._translate(RuntimeError("   ")).endswith("RuntimeError")


def test_the_detached_case_is_recognised_by_type_not_by_wording():
    """It used to be a bare ValueError, so this had to match on English message text. Since
    firmauy 1.10 it is typed, and an unrelated ValueError must not be mistaken for it."""
    assert backend._kind(ValueError("a non-empty PIN is required to sign")) == "other"
    assert not isinstance(_NEEDS_ORIGINAL, ValueError)


def test_the_detached_message_names_the_file_it_looked_for():
    """The picker is the fix, so the message has to say which file the signature covers."""
    assert "contrato.pdf" in backend._translate(_NEEDS_ORIGINAL)


def test_the_detached_message_survives_a_missing_expected_path():
    bare = DetachedOriginalRequiredError("needs its original")
    assert "archivo original" in backend._translate(bare)
    assert backend._kind(bare) == "needs_original"


def test_call_wraps_a_failure_instead_of_raising():
    def boom():
        raise CardNotFoundError("no card")

    result = backend._call(boom)
    assert result.ok is False
    assert result.value is None
    assert result.error_kind == "card"
    assert "cédula" in result.error


def test_call_passes_a_value_through():
    result = backend._call(lambda: [1, 2, 3])
    assert result == backend.Result(True, [1, 2, 3])


def test_an_unsigned_file_gets_its_own_sentence():
    """Dropping a file that is not signed at all is the most common wrong input Verificar sees,
    and the person deserves better than a technical fallback in English."""
    exc = ValueError("could not detect the signature type (not a PDF, XAdES XML or CMS/.p7s)")
    assert "no parece un archivo firmado" in backend._translate(exc)


def test_the_ca_progress_lines_speak_spanish():
    """firmauy narrates the CA download in English; the seam glosses the two shapes the app can
    meet (a retry, and the fall back to the pinned mirror) and lets anything unrecognised pass
    through rather than vanish."""
    assert backend._gloss_ca_progress(
        "www.uce.gub.uy: attempt 2/4 failed (timed out); retrying in 1.2s…") == (
        "www.uce.gub.uy: intento 2 de 4 falló (no respondió a tiempo); reintentando en 1.2s...")
    assert backend._gloss_ca_progress(
        "ca.minterior.gub.uy unavailable (HTTP 503); falling back to crt.sh…") == (
        "ca.minterior.gub.uy no responde (HTTP 503); probando con crt.sh...")
    line = "something new firmauy started saying"
    assert backend._gloss_ca_progress(line) == line


def test_refresh_cas_glosses_what_it_relays(monkeypatch):
    heard = []

    class _Bundle:
        root_path = "/tmp/acrn.pem"
        intermediate_path = "/tmp/mica.pem"
        cache_dir = "/tmp/national-ca"

    def fake(progress=None, **kw):
        progress("ca.minterior.gub.uy unavailable (HTTP 503); falling back to crt.sh…")
        return _Bundle()

    monkeypatch.setattr(backend, "_api_fetch_cas", fake)
    result = backend.refresh_cas(progress=heard.append)

    assert result.ok is True
    assert heard == ["ca.minterior.gub.uy no responde (HTTP 503); probando con crt.sh..."]
