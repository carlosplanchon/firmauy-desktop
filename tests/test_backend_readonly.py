# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the read-only side of the backend: introspection, CAs and the cédula number.

None of these needs a card, a PIN or a network, because firmauy.api is replaced at the alias.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from firmauy.api import CaBundle, CertInfo, CiReport, TokenInfo

from firmauy_desktop import backend


# --- readers, tokens and certificates ---------------------------------------

def test_list_readers_returns_the_names(monkeypatch):
    """These strings are exactly what the `reader` setting accepts, so they pass through raw."""
    monkeypatch.setattr(backend, "_api_list_readers",
                        lambda: ["ACS ACR38U-CCID 00 00", "Otro lector 01 00"])

    result = backend.list_readers()
    assert result.ok is True
    assert result.value == ["ACS ACR38U-CCID 00 00", "Otro lector 01 00"]


def test_list_readers_reports_a_broken_stack(monkeypatch):
    def boom():
        raise RuntimeError("pcscd is not running")

    monkeypatch.setattr(backend, "_api_list_readers", boom)

    result = backend.list_readers()
    assert result.ok is False
    assert result.value is None
    assert "pcscd" in result.error


def test_list_tokens_maps_and_forwards_the_module(monkeypatch):
    captured = {}

    def fake(*, pkcs11_lib):
        captured["pkcs11_lib"] = pkcs11_lib
        return [TokenInfo(label="CARLOS", manufacturer="Gemalto", model=None, serial="ABC")]

    monkeypatch.setattr(backend, "_api_list_tokens", fake)

    result = backend.list_tokens(pkcs11_lib="/lib.so")
    assert captured["pkcs11_lib"] == "/lib.so"
    assert result.value == [backend.Token("CARLOS", "Gemalto", "", "ABC")]  # None becomes ""


def test_list_tokens_is_empty_without_a_card(monkeypatch):
    monkeypatch.setattr(backend, "_api_list_tokens", lambda *, pkcs11_lib: [])
    assert backend.list_tokens() == backend.Result(True, [])


def test_list_certs_flattens_the_name_fields(monkeypatch):
    info = CertInfo(
        id="01",
        subject={"common_name": "PEREZ PEREZ JUAN", "serial_number": "12345672",
                 "organization": None, "country": "UY"},
        issuer={"common_name": "MINISTERIO DEL INTERIOR CA"},
        certificate_serial="0A1B",
        not_after="2032-02-15",
        digital_signature=True,
        pem="-----BEGIN CERTIFICATE-----",
    )
    monkeypatch.setattr(backend, "_api_list_certs",
                        lambda *, pkcs11_lib, include_pem: [info])

    cert = backend.list_certs(include_pem=True).value[0]
    assert cert.subject_common_name == "PEREZ PEREZ JUAN"
    assert cert.subject_serial_number == "12345672"   # the holder's cédula, as the cert spells it
    assert cert.issuer_common_name == "MINISTERIO DEL INTERIOR CA"
    assert cert.digital_signature is True
    assert cert.pem.startswith("-----BEGIN")


def test_list_certs_never_asks_for_a_pin(monkeypatch):
    """Cédula tokens do not gate their certificate list, and prompting would spend card tries
    to read public data."""
    captured = {}

    def fake(**kw):
        captured.update(kw)
        return []

    monkeypatch.setattr(backend, "_api_list_certs", fake)
    backend.list_certs()

    assert "pin" not in captured


# --- the national CAs -------------------------------------------------------

def test_refresh_cas_returns_the_paths_and_forwards_progress(monkeypatch):
    steps = []

    def fake(*, progress):
        progress("bajando la raíz")
        progress("bajando la intermedia")
        return CaBundle(root_path=Path("/c/acrn.cer"),
                        intermediate_path=Path("/c/mica.cer"),
                        cache_dir=Path("/c"))

    monkeypatch.setattr(backend, "_api_fetch_cas", fake)

    result = backend.refresh_cas(progress=steps.append)
    assert result.ok is True
    assert result.value == backend.CaPaths("/c/acrn.cer", "/c/mica.cer", "/c")
    assert steps == ["bajando la raíz", "bajando la intermedia"]


def test_refresh_cas_reports_a_failed_download(monkeypatch):
    def boom(*, progress):
        raise RuntimeError("fingerprint mismatch for the root certificate")

    monkeypatch.setattr(backend, "_api_fetch_cas", boom)

    result = backend.refresh_cas()
    assert result.ok is False
    assert "fingerprint" in result.error


# --- the cédula number ------------------------------------------------------

def test_check_ci_completes_a_body(monkeypatch):
    monkeypatch.setattr(backend, "_api_complete_ci", lambda body: body + "2")

    result = backend.check_ci("1234567")
    assert result.completed == "12345672"
    assert "12345672" in result.message
    assert result.ok is None                      # completing is neither valid nor invalid


def test_check_ci_validates_a_full_number(monkeypatch):
    monkeypatch.setattr(backend, "_api_validate_ci", lambda text: CiReport(
        valid=True, normalized="1.234.567-2", body="1234567",
        check_digit="2", expected_check_digit="2"))

    result = backend.check_ci("1.234.567-2")      # separators and all
    assert result.ok is True
    assert "consistente" in result.message


def test_check_ci_names_the_digit_it_expected(monkeypatch):
    monkeypatch.setattr(backend, "_api_validate_ci", lambda text: CiReport(
        valid=False, normalized="1.234.567-9", body="1234567",
        check_digit="9", expected_check_digit="2"))

    result = backend.check_ci("12345679")
    assert result.ok is False
    assert "debería ser 2" in result.message


@pytest.mark.parametrize("text", ["", "   ", "abc", "-.-"])
def test_check_ci_says_nothing_about_an_empty_field(text):
    assert backend.check_ci(text) == backend.CiResult()


def test_check_ci_hints_when_there_are_too_many_digits():
    result = backend.check_ci("123456789")
    assert "hasta 8" in result.message
    assert result.ok is None


def test_check_ci_never_raises(monkeypatch):
    """It runs on every keystroke, so a ValueError from firmauy has to come back as a message."""
    def boom(text):
        raise ValueError("cédula must be 8 digits")

    monkeypatch.setattr(backend, "_api_validate_ci", boom)

    result = backend.check_ci("12345672")
    assert result.ok is None
    assert "8 digits" in result.message


@pytest.mark.parametrize("text", ["²", "٣٤٥", "１２３４５６７", "١٢٣٤٥٦٧٨"])
def test_check_ci_reads_only_the_digits_a_cedula_is_written_in(text):
    """str.isdigit says yes to a superscript and to Arabic-Indic and full-width digits. The first
    raised out of int() and came back as a failure the app did not recognise, recorded as a
    crash. The others were checked as a cédula, and answered in mixed scripts."""
    assert backend.check_ci(text) == backend.CiResult()


def test_check_ci_keeps_the_digits_around_ones_it_does_not_read():
    """A footnote mark pasted along with a number is not part of it."""
    result = backend.check_ci("1234567²")

    assert result.completed == "12345672"


# --- the photo metadata -----------------------------------------------------

def test_read_identity_carries_the_photo_metadata(monkeypatch):
    from types import SimpleNamespace

    from firmauy.api import PhotoReport

    person = SimpleNamespace(
        given_names="ANA", lastnames="PEREZ", second_lastname=None, nationality=None,
        birth_date=None, birthplace=None, id_number="12345672",
        id_number_check_digit_valid=True, issue_date=None, expiry_date=None,
        document_number=None, mrz=None,
    )
    monkeypatch.setattr(backend, "_api_fetch_identity", lambda **kw: person)
    monkeypatch.setattr(backend, "_api_fetch_photo", lambda **kw: PhotoReport(
        data=b"\xff\xd8\xff", format="JPEG", mime="image/jpeg",
        width=240, height=320, size_bytes=3, sha256="abc"))

    identity = backend.read_identity().identity
    assert identity.photo == b"\xff\xd8\xff"
    assert identity.photo_meta == backend.Photo("JPEG", "image/jpeg", 240, 320, 3, "abc")


def test_a_broken_photo_report_costs_the_metadata_not_the_screen(monkeypatch):
    """If firmauy's PhotoReport ever loses a field, the biographic data must still show."""
    from types import SimpleNamespace

    person = SimpleNamespace(
        given_names="ANA", lastnames="PEREZ", second_lastname=None, nationality=None,
        birth_date=None, birthplace=None, id_number="12345672",
        id_number_check_digit_valid=True, issue_date=None, expiry_date=None,
        document_number=None, mrz=None,
    )
    monkeypatch.setattr(backend, "_api_fetch_identity", lambda **kw: person)
    monkeypatch.setattr(backend, "_api_fetch_photo",
                        lambda **kw: SimpleNamespace(data=b"\xff\xd8\xff"))   # no metadata

    result = backend.read_identity()
    assert result.ok is True
    assert result.identity.full_name == "ANA PEREZ"
    assert result.identity.photo_meta is None


# --- the sensitive flag -----------------------------------------------------

def test_run_doctor_carries_the_sensitive_flag(monkeypatch):
    """firmauy marks the checks whose detail can be the cardholder's own name."""
    from firmauy.api import DoctorCheck as ApiCheck
    from firmauy.api import DoctorReport

    monkeypatch.setattr(backend, "_api_run_doctor", lambda **kw: DoctorReport(ok=True, checks=[
        ApiCheck("PASS", "pcscd running", "active", None, False),
        ApiCheck("PASS", "cédula token detected", "CARLOS ANDRÉS ...", None, True),
    ]))

    checks = backend.run_doctor().checks
    assert [c.sensitive for c in checks] == [False, True]


def test_a_check_without_the_flag_is_treated_as_sensitive(monkeypatch):
    """An older firmauy should cost detail, not privacy."""
    from types import SimpleNamespace

    from firmauy.api import DoctorReport

    old_check = SimpleNamespace(status="PASS", name="algo", detail="x", fix=None)
    monkeypatch.setattr(backend, "_api_run_doctor",
                        lambda **kw: DoctorReport(ok=True, checks=[old_check]))

    assert backend.run_doctor().checks[0].sensitive is True


def test_a_bytes_attribute_is_decoded_not_repr_d(monkeypatch):
    """Real finding on a Gemalto middleware: TokenInfo.serial is annotated Optional[str] but
    comes back as bytes, and str() on bytes puts b'6600...' on the screen. Fixed upstream in
    firmauy too, but the app must never show a Python repr regardless."""
    monkeypatch.setattr(backend, "_api_list_tokens", lambda *, pkcs11_lib: [
        TokenInfo(label=b"GemP15-1\x00\x00", manufacturer=None, model="Classic V4",
                  serial=b"66000034D0201077"),
    ])

    token = backend.list_tokens().value[0]
    assert token.serial == "66000034D0201077"
    assert token.label == "GemP15-1"          # NUL padding is the attribute format, not the value
    assert "b'" not in token.serial
