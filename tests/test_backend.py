"""Unit tests for the firmauy_desktop backend.

The backend is the single seam between the Qt views and firmauy: it adapts the firmauy
public API (firmauy.api) results into the app's own small result dataclasses and turns any
error into a result the UI can render, never raising. These tests mock firmauy.api so they
need no card, no PIN and no Qt. The real signing is covered in firmauy's own suite (SoftHSM2
end-to-end tests of firmauy.api.sign); the backend's job here is only the mapping, the
error-to-Spanish translation, and the native-first defaults the app relies on.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from firmauy.api import (
    CardNotFoundError,
    DoctorCheck,
    DoctorReport,
    IncorrectPinError,
    OutputExistsError,
    PinFormatError,
    PinLastTryError,
    PinLockedError,
    ReaderNotFoundError,
    PhotoReport,
    SignReport,
    TimestampError,
    VerifyReport,
)

from firmauy_desktop import backend


def test_verify_file_maps_report(monkeypatch):
    """Everything the screen renders comes through here, including the fields the first version
    of this app threw away: trusted, each check's detail, and the full signer/issuer names."""
    sig = SimpleNamespace(
        indication="VALID",
        trusted=True,
        signer={"common_name": "PEREZ PEREZ JUAN", "serial_number": "DNI12345672",
                "organization": None, "country": "UY",
                "certificate_serial": "0A1B"},
        issuer={"common_name": "MI CA"},
        checks=[
            SimpleNamespace(name="integrity", ok=True, detail=""),
            SimpleNamespace(name="trust", ok=False, detail="no path to a trusted root"),
        ],
    )
    monkeypatch.setattr(
        backend, "_api_verify",
        lambda path, **kw: VerifyReport(indication="VALID", signatures=[sig]),
    )

    result = backend.verify_file("whatever.p7s")

    assert result.indication == "VALID"
    assert result.error is None
    assert result.signatures == [backend.Signature(
        indication="VALID",
        trusted=True,
        signer=backend.Party("PEREZ PEREZ JUAN", "DNI12345672", "", "UY", "0A1B"),
        issuer=backend.Party("MI CA"),
        checks=[
            backend.Check("integrity", True, ""),
            backend.Check("trust", False, "no path to a trusted root"),
        ],
    )]


def test_verify_file_catches_errors(monkeypatch):
    def boom(path, **kw):
        raise ValueError("bad file")

    monkeypatch.setattr(backend, "_api_verify", boom)

    result = backend.verify_file("x")

    assert result.indication == ""
    # Framed in Spanish and still carrying the detail, since it is what a report would need.
    assert result.error.startswith("Falló de una forma que la app no reconoce")
    assert "bad file" in result.error
    assert result.signatures == []


def test_run_doctor_maps_report_and_defaults_native(monkeypatch):
    report = DoctorReport(ok=True, checks=[
        DoctorCheck("PASS", "pcscd running", "", None),
        DoctorCheck("WARN", "cédula detected", "no card", "Insert the card."),
    ])
    captured = {}

    def fake(*, native, **kw):
        captured["native"] = native
        captured.update(kw)
        return report

    monkeypatch.setattr(backend, "_api_run_doctor", fake)

    result = backend.run_doctor()

    assert captured["native"] is True  # the app diagnoses the native path it signs with
    assert result.ok is True
    assert result.error is None
    assert [(c.status, c.name, c.detail, c.fix) for c in result.checks] == [
        ("PASS", "pcscd running", "", None),
        ("WARN", "cédula detected", "no card", "Insert the card."),
    ]


def test_run_doctor_catches_errors(monkeypatch):
    def boom(*, native, **kw):
        raise RuntimeError("no reader")

    monkeypatch.setattr(backend, "_api_run_doctor", boom)

    result = backend.run_doctor()

    assert result.ok is False
    assert result.error.startswith("Falló de una forma que la app no reconoce")
    assert "no reader" in result.error
    assert result.checks == []


def test_sign_file_maps_report_and_defaults_native(monkeypatch, tmp_path):
    # sign() auto-detects, so a PDF comes back as a signed PDF, not a detached .p7s.
    out = tmp_path / "doc_firmado.pdf"
    captured = {}

    def fake(path, pin, *, pin_provider, native, **kw):
        captured.update(path=path, pin=pin, native=native)
        return SignReport(output_path=out, signer="PEREZ PEREZ JUAN", issuer="MI CA",
                          kind="pades", backend="native")

    monkeypatch.setattr(backend, "_api_sign", fake)

    result = backend.sign_file("doc.pdf", "1234")

    assert captured == {"path": "doc.pdf", "pin": "1234", "native": True}
    assert result.ok is True
    assert result.output_path == str(out)
    assert result.detail == str(out)


def test_sign_file_catches_generic_errors(monkeypatch):
    def boom(path, pin, *, pin_provider, native, **kw):
        raise ValueError("a non-empty PIN is required to sign")

    monkeypatch.setattr(backend, "_api_sign", boom)

    result = backend.sign_file("doc.pdf", "")

    assert result.ok is False
    assert result.output_path is None
    assert "PIN" in result.detail


def _sign_raising(monkeypatch, exc):
    def boom(path, pin, *, pin_provider, native, **kw):
        raise exc

    monkeypatch.setattr(backend, "_api_sign", boom)
    return backend.sign_file("doc.pdf", "1234")


@pytest.mark.parametrize("attempts, expected", [
    (2, "Te quedan 2 intentos"),
    (1, "Te queda 1 intento"),          # singular, and warns the card is one try from locking
    (None, "PIN incorrecto."),          # PKCS#11 cannot report a count
])
def test_sign_file_translates_incorrect_pin(monkeypatch, attempts, expected):
    result = _sign_raising(monkeypatch, IncorrectPinError("Incorrect PIN.",
                                                          attempts_remaining=attempts))
    assert result.ok is False
    assert expected in result.detail


def test_sign_file_translates_locked_pin(monkeypatch):
    result = _sign_raising(monkeypatch, PinLockedError("The PIN is blocked."))
    assert result.ok is False
    assert "bloqueado" in result.detail


def test_sign_file_translates_missing_reader_and_card(monkeypatch):
    result = _sign_raising(monkeypatch, ReaderNotFoundError("No PC/SC readers found."))
    assert "lector" in result.detail

    result = _sign_raising(monkeypatch, CardNotFoundError("No card found."))
    assert "cédula" in result.detail


def test_sign_file_translates_existing_output(monkeypatch, tmp_path):
    exc = OutputExistsError("Output file already exists", path=tmp_path / "doc_firmado.pdf")
    result = _sign_raising(monkeypatch, exc)
    assert result.ok is False
    assert "doc_firmado.pdf" in result.detail
    assert "Ya existe" in result.detail


def test_sign_file_passes_the_pin_provider_through(monkeypatch, tmp_path):
    """With pin_provider the backend hands the callback to firmauy, which calls it when the
    card is ready (mirrored here by invoking it), instead of collecting the PIN up front."""
    out = tmp_path / "doc_firmado.pdf"
    captured = {}

    def fake(path, pin, *, pin_provider, native, **kw):
        captured.update(path=path, pin=pin, native=native)
        captured["pin_from_provider"] = pin_provider()      # firmauy calls it at the right moment
        return SignReport(output_path=out, signer="PEREZ PEREZ JUAN", issuer="MI CA", kind="pades")

    monkeypatch.setattr(backend, "_api_sign", fake)

    result = backend.sign_file("doc.pdf", pin_provider=lambda: "1234")

    assert captured["pin"] is None                          # no PIN was collected up front
    assert captured["pin_from_provider"] == "1234"
    assert captured["native"] is True
    assert result.ok is True
    assert result.output_path == str(out)


def test_sign_file_reports_a_cancelled_pin_prompt(monkeypatch):
    """Dismissing the PIN dialog raises PinCancelled from the provider; it must come back as a
    plain cancelled result, not as an error message."""
    def fake(path, pin, *, pin_provider, native, **kw):
        pin_provider()                                      # the user cancels here
        raise AssertionError("signing must not continue after a cancelled prompt")

    monkeypatch.setattr(backend, "_api_sign", fake)

    def cancelling_provider():
        raise backend.PinCancelled

    result = backend.sign_file("doc.pdf", pin_provider=cancelling_provider)

    assert result.ok is False
    assert result.output_path is None
    assert result.detail == "Firma cancelada."


def test_a_pin_turned_down_before_the_prompt_says_to_unblock_the_card(monkeypatch):
    """firmauy reads the retry counter before it calls the provider, and turns a card on its last
    try away. The prompt never opened, and the answer is about the card."""
    prompted = []

    def provider():
        prompted.append(True)
        return "1234"

    def fake(path, pin, *, pin_provider, native, **kw):
        raise PinLastTryError("Only 1 PIN try left: aborting for safety.")

    monkeypatch.setattr(backend, "_api_sign", fake)

    result = backend.sign_file("doc.pdf", pin_provider=provider)

    assert prompted == []
    assert result.ok is False
    assert result.error_kind == "pin_last_try"
    assert "desbloquearla" in result.detail


def test_a_pin_turned_down_after_the_prompt_says_to_type_it_again(monkeypatch):
    def fake(path, pin, *, pin_provider, native, **kw):
        pin_provider()                                      # the dialog opens and answers
        raise PinFormatError("The cédula's PIN is digits only; aborting before contacting the card")

    monkeypatch.setattr(backend, "_api_sign", fake)

    result = backend.sign_file("doc.pdf", pin_provider=lambda: "12a4")

    assert result.error_kind == "pin_format"
    assert "entre 4 y 8 dígitos" in result.detail


def test_a_last_try_found_after_the_prompt_is_still_about_the_card(monkeypatch):
    """The direct path counts the tries again right before it sends the PIN, so a card can come
    down to its last try between the prompt and the send. Told apart by when the prompt had run,
    this read as a PIN of the wrong shape and asked for it again, which no PIN can fix."""
    def fake(path, pin, *, pin_provider, native, **kw):
        pin_provider()                                      # the dialog opens and answers
        raise PinLastTryError("Only 1 PIN try left: aborting for safety.")

    monkeypatch.setattr(backend, "_api_sign", fake)

    result = backend.sign_file("doc.pdf", pin_provider=lambda: "1234")

    assert result.error_kind == "pin_last_try"
    assert "desbloquearla" in result.detail


def test_a_pin_refusal_is_not_recorded_as_a_crash(monkeypatch):
    """The crash entry is for failures the app has no sentence for. A refusal it can explain is
    not one, and recording it as one would bury the real crashes in a file meant for a report."""
    crashes = []
    monkeypatch.setattr(backend.activity, "crash", crashes.append)

    def fake(path, pin, *, pin_provider, native, **kw):
        raise PinLastTryError("Only 1 PIN try left: aborting for safety.")

    monkeypatch.setattr(backend, "_api_sign", fake)
    backend.sign_file("doc.pdf", pin_provider=lambda: "1234")

    assert crashes == []


def test_a_timestamp_that_does_not_come_back_is_named_and_is_not_a_crash(monkeypatch):
    """After the PIN, so the card has signed: what is lost is the stamp, and with it the output.
    The sentence says that rather than that something unknown happened."""
    crashes = []
    monkeypatch.setattr(backend.activity, "crash", crashes.append)

    def fake(path, pin, *, pin_provider, native, **kw):
        pin_provider()
        raise TimestampError("Error in communication with timestamp server")

    monkeypatch.setattr(backend, "_api_sign", fake)
    result = backend.sign_file("doc.pdf", pin_provider=lambda: "1234",
                               tsa_url="https://tsa.example/tsr")

    assert result.ok is False
    assert result.output_path is None
    assert result.error_kind == "tsa_failed"
    assert "sello de tiempo" in result.detail
    assert crashes == []


# --- reading the cédula (no PIN) --------------------------------------------

_PERSON = SimpleNamespace(
    given_names="CARLOS ANDRÉS", lastnames="PLANCHÓN", second_lastname="PRESTES",
    nationality="ORIENTAL", birth_date="1990-01-01", birthplace="MONTEVIDEO",
    id_number="12345672", id_number_check_digit_valid=True,
    issue_date="2022-02-15", expiry_date="2032-02-15",
    document_number="D1234567", mrz=["...", "..."],
)

_PHOTO = PhotoReport(
    data=b"\xff\xd8\xff jpeg", format="JPEG", mime="image/jpeg",
    width=240, height=320, size_bytes=14, sha256="abc123",
)


def test_read_identity_maps_the_card_and_the_photo(monkeypatch):
    monkeypatch.setattr(backend, "_api_fetch_identity", lambda **kw: _PERSON)
    monkeypatch.setattr(backend, "_api_fetch_photo",
                        lambda **kw: _PHOTO)

    result = backend.read_identity()

    assert result.ok is True and result.error is None
    person = result.identity
    # Given names first, then both surnames, the way a cédula reads.
    assert person.full_name == "CARLOS ANDRÉS PLANCHÓN PRESTES"
    assert person.id_number == "12345672"
    assert person.id_number_valid is True
    assert person.birth_date == "1990-01-01"
    assert person.document_number == "D1234567"   # the card's own number, not the cédula number
    assert person.issue_date == "2022-02-15"
    assert person.expiry_date == "2032-02-15"
    assert person.photo == b"\xff\xd8\xff jpeg"


def test_read_identity_survives_a_missing_photo(monkeypatch):
    # The biographic data is worth showing even when the photo cannot be read.
    def no_photo(**kw):
        raise RuntimeError("No JPEG image found in file 7004.")

    monkeypatch.setattr(backend, "_api_fetch_identity", lambda **kw: _PERSON)
    monkeypatch.setattr(backend, "_api_fetch_photo", no_photo)

    result = backend.read_identity()

    assert result.ok is True
    assert result.identity.photo is None
    assert result.identity.full_name == "CARLOS ANDRÉS PLANCHÓN PRESTES"


def test_read_identity_translates_a_missing_card(monkeypatch):
    def no_card(**kw):
        raise CardNotFoundError("No card found in reader.")

    monkeypatch.setattr(backend, "_api_fetch_identity", no_card)

    result = backend.read_identity()

    assert result.ok is False
    assert result.identity is None
    assert "cédula" in result.error


def test_read_identity_translates_a_missing_reader(monkeypatch):
    def no_reader(**kw):
        raise ReaderNotFoundError("No PC/SC readers found.")

    monkeypatch.setattr(backend, "_api_fetch_identity", no_reader)
    assert "lector" in backend.read_identity().error


def test_full_name_skips_the_fields_the_card_omits():
    person = SimpleNamespace(given_names="ANA", lastnames="PEREZ", second_lastname=None)
    assert backend._full_name(person) == "ANA PEREZ"


# --- the options the app's settings decide ----------------------------------

def test_sign_file_forwards_the_backend_options(monkeypatch, tmp_path):
    """These come from Ajustes through settings.sign_kwargs, so they must reach firmauy intact."""
    captured = {}

    def fake(path, pin, **kw):
        captured.update(kw)
        return SignReport(output_path=tmp_path / "out.p7s", signer="X", issuer="Y")

    monkeypatch.setattr(backend, "_api_sign", fake)

    backend.sign_file("doc.pdf", "1234", native=False, reader="ACS",
                      pkcs11_lib="/lib.so", tsa_url="https://t", allow_private_network=True,
                      verify=True)

    assert captured["native"] is False
    assert captured["reader"] == "ACS"
    assert captured["pkcs11_lib"] == "/lib.so"
    assert captured["tsa_url"] == "https://t"
    assert captured["allow_private_network"] is True
    assert captured["verify"] is True


def test_verify_file_forwards_the_original_and_revocation(monkeypatch):
    captured = {}

    def fake(path, **kw):
        captured.update(kw)
        return VerifyReport(indication="VALID", signatures=[])

    monkeypatch.setattr(backend, "_api_verify", fake)

    backend.verify_file("data.bin.p7s", original="data.bin", check_revocation=True,
                        tsa_ca="/anchors.pem", allow_private_network=True)

    assert captured == {"original": "data.bin", "check_revocation": True,
                        "tsa_ca": "/anchors.pem", "allow_private_network": True}


def test_verify_file_stays_offline_by_default(monkeypatch):
    """Revocation checking is the only network I/O in verification, and it can hang."""
    captured = {}

    def fake(path, **kw):
        captured.update(kw)
        return VerifyReport(indication="VALID", signatures=[])

    monkeypatch.setattr(backend, "_api_verify", fake)
    backend.verify_file("firmado.pdf")

    assert captured["check_revocation"] is False
    assert captured["original"] is None


def test_run_doctor_forwards_the_reader_and_module(monkeypatch):
    captured = {}

    def fake(**kw):
        captured.update(kw)
        return DoctorReport(ok=True, checks=[])

    monkeypatch.setattr(backend, "_api_run_doctor", fake)
    backend.run_doctor(native=False, reader="ACS", pkcs11_lib="/lib.so")

    assert captured == {"native": False, "reader": "ACS", "pkcs11_lib": "/lib.so"}


def test_read_identity_forwards_the_reader_to_both_card_reads(monkeypatch):
    seen = []

    monkeypatch.setattr(backend, "_api_fetch_identity",
                        lambda **kw: seen.append(("identity", kw)) or _PERSON)
    monkeypatch.setattr(backend, "_api_fetch_photo",
                        lambda **kw: seen.append(("photo", kw)) or _PHOTO)

    backend.read_identity(reader="ACS")

    assert seen == [("identity", {"reader": "ACS"}), ("photo", {"reader": "ACS"})]


# --- the timestamp ----------------------------------------------------------

def _report_with(timestamp):
    """A firmauy report whose one signature carries ``timestamp``, in pyhanko-free shape."""
    sig = SimpleNamespace(indication="VALID", trusted=True, signer={}, issuer={}, checks=[],
                          timestamp=timestamp)
    return VerifyReport(indication="VALID", signatures=[sig])


def _info(**kw):
    from firmauy.verify_common import TimestampInfo
    return TimestampInfo(**kw)


def test_a_timestamp_is_carried_across_whole(monkeypatch):
    from datetime import datetime, timezone

    when = datetime(2026, 7, 30, 14, 32, 11, tzinfo=timezone.utc)
    monkeypatch.setattr(backend, "_api_verify", lambda path, **kw: _report_with(_info(
        present=True, intact=True, valid=True, trusted=None, gen_time=when,
        tsa_common_name="Sellado de Tiempo Ejemplo CA", detail="genTime ... (asserted)")))

    ts = backend.verify_file("firmado.pdf").signatures[0].timestamp

    assert ts == backend.Timestamp(
        present=True, intact=True, valid=True, trusted=None, gen_time=when,
        tsa="Sellado de Tiempo Ejemplo CA", detail="genTime ... (asserted)")


def test_never_evaluated_does_not_become_evaluated_and_failed(monkeypatch):
    """The distinction firmauy restored, and the one line of this mapping that could throw it
    away again: bool(None) is False, and False here is a claim nobody made."""
    monkeypatch.setattr(backend, "_api_verify", lambda path, **kw: _report_with(_info(
        present=True, intact=True, valid=True, trusted=None)))

    assert backend.verify_file("firmado.pdf").signatures[0].timestamp.trusted is None


def test_a_chain_that_was_evaluated_and_failed_keeps_its_false(monkeypatch):
    monkeypatch.setattr(backend, "_api_verify", lambda path, **kw: _report_with(_info(
        present=True, intact=True, valid=True, trusted=False)))

    assert backend.verify_file("firmado.pdf").signatures[0].timestamp.trusted is False


def test_no_timestamp_comes_through_as_none(monkeypatch):
    monkeypatch.setattr(backend, "_api_verify", lambda path, **kw: _report_with(None))

    assert backend.verify_file("firmado.pdf").signatures[0].timestamp is None


def test_a_report_that_says_present_is_false_is_not_a_timestamp(monkeypatch):
    """firmauy returns None rather than an absent-flagged object, but the field is a default and
    a future path could leave one behind. present=False means there is nothing to show."""
    monkeypatch.setattr(backend, "_api_verify",
                        lambda path, **kw: _report_with(_info(present=False)))

    assert backend.verify_file("firmado.pdf").signatures[0].timestamp is None


def test_an_older_firmauy_costs_the_row_and_nothing_else(monkeypatch):
    """The floor in pyproject is 1.12.0, so this is belt and braces, not the supported path. It
    is the same bargain the `sensitive` flag on a doctor check already makes: an older core loses
    one field instead of raising AttributeError through the whole screen.
    """
    sig = SimpleNamespace(indication="VALID", trusted=True, signer={}, issuer={},
                          checks=[SimpleNamespace(name="integrity", ok=True, detail="")])
    assert not hasattr(sig, "timestamp")
    monkeypatch.setattr(backend, "_api_verify",
                        lambda path, **kw: VerifyReport(indication="VALID", signatures=[sig]))

    result = backend.verify_file("firmado.pdf")

    assert result.signatures[0].timestamp is None
    assert result.signatures[0].checks == [backend.Check("integrity", True, "")]


def test_sound_is_the_token_holding_up_and_says_nothing_about_who_issued_it():
    assert backend.Timestamp(present=True, intact=True, valid=True).sound is True
    assert backend.Timestamp(present=True, intact=True, valid=False).sound is False
    assert backend.Timestamp(present=True, intact=False, valid=True).sound is False
    # Trust is a separate question and must not leak into this one.
    assert backend.Timestamp(present=True, intact=True, valid=True, trusted=False).sound is True
    # Never evaluated is not sound: nothing was checked.
    assert backend.Timestamp(present=True).sound is False


def test_verify_file_asks_for_nothing_about_the_tsa_by_default(monkeypatch):
    """The anchors are on the machine either way. Reaching for them unasked would mean the app
    decided who is trusted to say when a document was signed, which nobody delegated to it."""
    captured = {}

    def fake(path, **kw):
        captured.update(kw)
        return VerifyReport(indication="VALID", signatures=[])

    monkeypatch.setattr(backend, "_api_verify", fake)
    backend.verify_file("firmado.pdf")

    assert captured["tsa_ca"] is None


def test_a_bad_tsa_certificate_says_which_field_to_fix(monkeypatch):
    """The only file the app asks a person to supply by path is the TSA certificate in Ajustes,
    so pointing that field at the wrong file is the likeliest way to reach this. cryptography
    raises a bare ValueError in English, which on a Spanish screen names nothing to go fix."""
    def fake(path, **kw):
        raise ValueError("Unable to load PEM file. See https://cryptography.io/...")

    monkeypatch.setattr(backend, "_api_verify", fake)
    result = backend.verify_file("firmado.pdf", tsa_ca="/no/es/un.pem")

    assert "certificado de la TSA" in result.error
    assert "Ajustes" in result.error
    assert "PEM file" not in result.error
