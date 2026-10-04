# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Synthetic backend results, for the tests and for the storybook.

Everything here is invented. CONTRIBUTING forbids real names, document numbers, MRZ data,
photos or certificates anywhere in the repo, and keeping the synthetic cardholder in exactly one
file is what makes that rule enforceable instead of aspirational.

The long-value samples are not padding. Every fixture being short is how a layout ships with a
wrapping bug nobody saw: a sha256 and a sixty-character common name are what real cards and real
certificates actually contain.
"""

from __future__ import annotations

import platform
from datetime import datetime, timezone
from importlib.metadata import version as _installed_version

from firmauy_desktop import backend

_SHA256 = "96ccc62287f54cfa28c8ec24c6f960b7da403a0c4100c3d32c50e37fa7a73764"
_ISSUER = "Autoridad Certificadora del Ministerio del Interior"
# Invented, like everything else here. A real accredited provider's name in a fixture would read
# as an endorsement, and which providers are accredited is the UCE's business, not this repo's.
_TSA = "Sellado de Tiempo Ejemplo CA"

# The version row Diagnóstico shows, built the way firmauy builds it rather than copied from a run
# of it. Everything else in this file is invented on purpose, and this is the one value that must
# not be: it is not a sample, it is a fact about the machine the screenshot was taken on. Typed in,
# it went stale silently and the README showed the app running on a core its own floor has refused
# for several releases. Derived, a regenerated screenshot cannot disagree with the environment it
# was regenerated in.
_FIRMAUY_VERSION = f"{_installed_version('firmauy')} (Python {platform.python_version()})"


# --- the cardholder ---------------------------------------------------------

def identity(*, photo: bool = False, long_values: bool = False) -> backend.Identity:
    """A synthetic cédula. ``photo`` attaches a generated grey rectangle, never a face."""
    name = ("MARÍA DE LOS ÁNGELES RODRÍGUEZ FERNÁNDEZ DE LA CUESTA" if long_values
            else "JUANA MARÍA PÉREZ GONZÁLEZ")
    data = None
    meta = None
    if photo:
        data = photo_bytes()
        meta = backend.Photo("jpeg", "image/jpeg", 240, 320, len(data), _SHA256)
    return backend.Identity(
        full_name=name,
        id_number="1.234.567-2",
        id_number_valid=True,
        birth_date="1990-01-15",
        birthplace="MONTEVIDEO",
        nationality="URUGUAYA",
        document_number="A123456",
        issue_date="2022-03-01",
        expiry_date="2032-03-01",
        photo=data,
        photo_meta=meta,
    )


def photo_bytes() -> bytes:
    """A plain rectangle in JPEG. Generated rather than committed, so no image of a person
    ever lands in the repository."""
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage

    image = QImage(240, 320, QImage.Format.Format_RGB32)
    image.fill(QColor("#8fa3b8"))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "JPEG")
    return bytes(buffer.data())


def identity_read(**kwargs) -> backend.IdentityResult:
    return backend.IdentityResult(True, identity(**kwargs))


def identity_no_card() -> backend.IdentityResult:
    return backend.IdentityResult(
        False, error="No se detectó la cédula en el lector. Insertala e intentá de nuevo.",
        error_kind="card")


# --- verification -----------------------------------------------------------

def _signature(*, indication: str = "VALID", trusted: bool = True,
               signer: str = "PEREZ PEREZ JUAN",
               timestamp: backend.Timestamp | None = None) -> backend.Signature:
    checks = [
        backend.Check("signature intact (covered bytes unmodified)", True),
        backend.Check("signature cryptographically valid", True),
        backend.Check("coverage (whole file)", True),
        backend.Check("certificate chain to trusted root", trusted,
                      "" if trusted else "not trusted"),
    ]
    if timestamp is not None:
        # The row firmauy emits alongside the structured object, so the technical fold looks the
        # way it will in practice rather than showing the object with no check to match it.
        checks.append(backend.Check(
            "signature timestamp present (TSA not trust-validated)",
            timestamp.sound,
            timestamp.detail,
        ))
    return backend.Signature(
        indication=indication,
        trusted=trusted,
        signer=backend.Party(signer, "DNI12345672", "", "UY", "781910B3462611FA69C417C6AAE1BFEE"),
        issuer=backend.Party(_ISSUER),
        checks=checks,
        timestamp=timestamp,
    )


# A fixed instant, so a storybook screenshot does not change every time it is taken. UTC, the way
# an RFC 3161 genTime arrives.
_GEN_TIME = datetime(2026, 7, 30, 14, 32, 11, tzinfo=timezone.utc)


def _stamp(*, sound: bool = True, trusted: bool | None = None) -> backend.Timestamp:
    if not sound:
        return backend.Timestamp(present=True, intact=False, valid=False, trusted=trusted,
                                 gen_time=_GEN_TIME, tsa=_TSA,
                                 detail="timestamp token signature is invalid")
    detail = (f"genTime {_GEN_TIME.isoformat()} "
              + ("(trusted)" if trusted else "(asserted by the TSA, not verified)"))
    return backend.Timestamp(present=True, intact=True, valid=True, trusted=trusted,
                             gen_time=_GEN_TIME, tsa=_TSA, detail=detail)


def verify_valid(signers: int = 1) -> backend.VerifyResult:
    return backend.VerifyResult("VALID", [_signature() for _ in range(signers)])


def verify_indeterminate() -> backend.VerifyResult:
    return backend.VerifyResult("INDETERMINATE",
                                [_signature(indication="INDETERMINATE", trusted=False)])


def verify_invalid() -> backend.VerifyResult:
    sig = _signature(indication="INVALID")
    sig.checks[0] = backend.Check("signature intact (covered bytes unmodified)", False,
                                  "the signed bytes changed after signing")
    return backend.VerifyResult("INVALID", [sig])


def verify_long_values() -> backend.VerifyResult:
    """The state that surfaces a grid refusing to wrap. Deliberately unreasonable, and real."""
    sig = _signature(signer="MARÍA DE LOS ÁNGELES RODRÍGUEZ FERNÁNDEZ DE LA CUESTA")
    sig.checks.append(backend.Check(
        "signature timestamp present (XAdES-T, TSA not trust-validated)", True, _SHA256))
    return backend.VerifyResult("VALID", [sig])


def verify_timestamped() -> backend.VerifyResult:
    """A sound stamp whose TSA chain was never evaluated. The ordinary case: this app supplies no
    TSA anchors, so every real stamp it reports lands here."""
    return backend.VerifyResult("VALID", [_signature(timestamp=_stamp())])


def verify_broken_timestamp() -> backend.VerifyResult:
    """A sound signature and a broken token. The state that says the two verdicts are separate:
    everything about the signature passes, and the file is still not VÁLIDO."""
    return backend.VerifyResult(
        "INDETERMINATE",
        [_signature(indication="INDETERMINATE", timestamp=_stamp(sound=False))],
    )


def verify_needs_original() -> backend.VerifyResult:
    return backend.VerifyResult(
        "", error="Este .p7s está separado del archivo que firmó. Se buscó contrato.pdf al lado "
                  "y no está. ¿Cuál es?",
        error_kind="needs_original")


def verify_error() -> backend.VerifyResult:
    return backend.VerifyResult(
        "", error="Esto no parece un archivo firmado: no es un PDF firmado, un XML firmado "
                  "(XAdES) ni un .p7s.",
        error_kind="other")


def verify_batch_all_valid(n: int = 3) -> backend.BatchVerifyResult:
    return backend.BatchVerifyResult(True, [
        backend.VerifiedItem(p, verify_valid()) for p in batch_paths(n)])


def verify_batch_mixed() -> backend.BatchVerifyResult:
    """One of every answer a batch row can carry, in a single state, so the counts sentence,
    the row icons and the drill-down all get walked by the storybook run in CI on every push."""
    paths = batch_paths(3) + ["/home/ana/documentos/convenio.pdf.p7s",
                              "/home/ana/documentos/anexo.xml"]
    return backend.BatchVerifyResult(True, [
        backend.VerifiedItem(paths[0], verify_valid()),
        backend.VerifiedItem(paths[1], verify_indeterminate()),
        backend.VerifiedItem(paths[2], verify_invalid()),
        backend.VerifiedItem(paths[3], backend.VerifyResult(
            "", error="Este .p7s está separado del archivo que firmó. Se buscó convenio.pdf "
                      "al lado y no está. ¿Cuál es?", error_kind="needs_original")),
        backend.VerifiedItem(paths[4], verify_error()),
    ])


# --- the environment --------------------------------------------------------

def doctor_healthy() -> backend.DoctorResult:
    return backend.DoctorResult(True, [
        backend.DoctorCheck("PASS", "firmauy", _FIRMAUY_VERSION, None, False),
        backend.DoctorCheck("PASS", "pcscd running", "", None, False),
        backend.DoctorCheck("PASS", "PC/SC reader detected", "ACS ACR 38U-CCID 00 00", None,
                            False),
        backend.DoctorCheck("PASS", "cédula detected", "IAS applet selected", None, False),
        backend.DoctorCheck("PASS", "bundled national CA certificates",
                            "root + intermediate loaded", None, False),
    ])


def doctor_broken() -> backend.DoctorResult:
    """Every string here is one firmauy really emits, copied rather than invented.

    It used to carry Spanish repair texts of its own making, so the storybook and the README's
    screenshot showed a screen that was fully translated while the real one was not. A sample
    that is kinder than reality hides the work instead of showing it.
    """
    return backend.DoctorResult(False, [
        backend.DoctorCheck("PASS", "firmauy", _FIRMAUY_VERSION, None, False),
        backend.DoctorCheck("WARN", "pcscd running", "installed but not running",
                            "Start it: sudo systemctl enable --now pcscd", False),
        backend.DoctorCheck("WARN", "PC/SC reader detected", "none found",
                            "Connect a reader and make sure pcscd is running.", False),
        backend.DoctorCheck("FAIL", "bundled national CA certificates", "not loadable",
                            "The package install looks broken; reinstall firmauy.", False),
    ])


def doctor_truncated() -> backend.DoctorResult:
    """firmauy returns early on a failing check, so a real list can be this short."""
    return backend.DoctorResult(False, [
        backend.DoctorCheck("WARN", "PC/SC reader detected", "not found",
                            "Connect a reader and make sure pcscd is running.", False),
    ])


def doctor_sensitive() -> backend.DoctorResult:
    """The PKCS#11 branch, where the token label can be the cardholder's own name."""
    return backend.DoctorResult(True, [
        backend.DoctorCheck("PASS", "firmauy", _FIRMAUY_VERSION, None, False),
        backend.DoctorCheck("PASS", "PKCS#11 module present", "/usr/lib/pkcs11/libgclib.so",
                            None, False),
        backend.DoctorCheck("PASS", "PKCS#11 module loads", "", None, False),
        backend.DoctorCheck("PASS", "cédula token detected", "JUANA MARÍA PÉREZ GONZÁLEZ",
                            None, True),
    ])


def readers() -> backend.Result:
    return backend.Result(True, ["ACS ACR 38U-CCID 00 00", "Otro lector 01 00"])


def cas_refreshed() -> backend.Result:
    return backend.Result(True, backend.CaPaths(
        "/home/ana/.cache/firmauy/national-ca/acrn.cer",
        "/home/ana/.cache/firmauy/national-ca/mica.cer",
        "/home/ana/.cache/firmauy/national-ca"))


# --- the token --------------------------------------------------------------

def tokens() -> backend.Result:
    return backend.Result(True, [
        backend.Token("GemP15-1", "", "Classic V4", "66000034D0201077"),
    ])


def no_tokens() -> backend.Result:
    return backend.Result(True, [])


def certs(*, pem: bool = True) -> backend.Result:
    return backend.Result(True, [
        backend.Cert(
            id="5c10d3cbb03a4b6865acdd16c6eecd2c08eb7c47",
            subject_common_name="PEREZ PEREZ JUAN",
            subject_serial_number="DNI12345672",
            issuer_common_name=_ISSUER,
            certificate_serial="781910B3462611FA69C417C6AAE1BFEE",
            not_after="2031-03-25",
            digital_signature=True,
            pem="-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n" if pem else None,
        ),
    ])


def module_error() -> backend.Result:
    return backend.Result(False, None, "no such file: /usr/lib/pkcs11/libgclib.so", "other")


# --- signing ----------------------------------------------------------------

def signed(*, kind: str = "pades") -> backend.SignResult:
    return backend.SignResult(
        True, "/home/ana/contrato_firmado.pdf", "/home/ana/contrato_firmado.pdf",
        kind=kind, backend="native", signer="PEREZ PEREZ JUAN", issuer=_ISSUER,
        certificate_serial="781910B3462611FA69C417C6AAE1BFEE", verified=True)


def wrong_pin(tries: int | None = 2) -> backend.SignResult:
    if tries == 1:
        detail = "PIN incorrecto. Te queda 1 intento antes de que se bloquee."
    elif tries is None:
        detail = "PIN incorrecto."
    else:
        detail = f"PIN incorrecto. Te quedan {tries} intentos."
    return backend.SignResult(False, None, detail, "pin")


def output_exists() -> backend.SignResult:
    return backend.SignResult(
        False, None, "Ya existe contrato_firmado.pdf. Movelo o renombralo si querés firmar de "
                     "nuevo.", "output_exists",
        conflict_path="/home/ana/contrato_firmado.pdf")


def batch_paths(n: int = 3) -> list[str]:
    return [f"/home/ana/documentos/acta-{i + 1}.pdf" for i in range(n)]


def batch_all_signed(n: int = 3) -> backend.BatchSignResult:
    return backend.BatchSignResult(True, [
        backend.SignedItem(p, p.replace(".pdf", "_firmado.pdf"), "signed")
        for p in batch_paths(n)
    ])


def batch_partial() -> backend.BatchSignResult:
    paths = batch_paths(4)
    return backend.BatchSignResult(False, [
        backend.SignedItem(paths[0], paths[0].replace(".pdf", "_firmado.pdf"), "signed"),
        backend.SignedItem(paths[1], paths[1].replace(".pdf", "_firmado.pdf"), "signed"),
        backend.SignedItem(paths[2], "", "failed", "Ya existe acta-3_firmado.pdf."),
        backend.SignedItem(paths[3]),
    ], "Ya existe acta-3_firmado.pdf.", "output_exists")


def batch_warned() -> backend.BatchSignResult:
    """A batch stopped by the one failure that happens after the file is already written.

    The first file signs, its permissions cannot be set, and firmauy raises. So the only output
    this batch produced is a warned one, and for a while that combination crashed the screen:
    the count of what was signed included it and the search for something to open did not. This
    state exists so the storybook run in CI walks that path on every push.
    """
    paths = batch_paths(3)
    return backend.BatchSignResult(False, [
        backend.SignedItem(paths[0], paths[0].replace(".pdf", "_firmado.pdf"), "warned",
                           "Se firmó y quedó guardado, pero no se pudieron ajustar los permisos."),
        backend.SignedItem(paths[1]),
        backend.SignedItem(paths[2]),
    ], "Se firmó y quedó guardado, pero no se pudieron ajustar los permisos.", "output_committed")


def batch_cancelled() -> backend.BatchSignResult:
    paths = batch_paths(4)
    return backend.BatchSignResult(False, [
        backend.SignedItem(paths[0], paths[0].replace(".pdf", "_firmado.pdf"), "signed"),
        backend.SignedItem(paths[1]),
        backend.SignedItem(paths[2]),
        backend.SignedItem(paths[3]),
    ], "", "cancelled")


# --- the cédula number ------------------------------------------------------

def ci_consistent() -> backend.CiResult:
    return backend.CiResult("El número es consistente.", ok=True)


def ci_inconsistent() -> backend.CiResult:
    return backend.CiResult(
        "No es consistente: el dígito verificador debería ser 2.", ok=False)


def ci_completed() -> backend.CiResult:
    return backend.CiResult("Con dígito verificador: 12345672", completed="12345672")
