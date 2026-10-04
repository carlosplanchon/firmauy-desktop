# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""A signed PDF and the anchor that judges it, generated rather than committed.

What this is for: CI builds a PyInstaller bundle and checks that it starts and that its icons
draw. Neither of those touches the thing the app is for. ``--selftest-verify`` puts a real
signature through the frozen core, which is the only check that exercises firmauy, pyHanko,
cryptography and their plugins as they were actually packed.

That needs a signed file, and the obvious one cannot exist. A fixture that verifies VALID against
the national anchors would have to be signed by a real cédula, and the anchors are pinned by
fingerprint so nothing else reaches them. Measured: the same synthetic file comes back
INDETERMINATE with no anchors and VALID against its own.

So the bundle is asked for INDETERMINATE, which still walks the PDF, the CMS, the certificate
parsing and the chain building and stops one step short of a successful chain. Handing the shipped
binary an anchor of its own would close that gap and is the thing SECURITY.md refuses, since a
build that accepts a certificate authority turns "install this certificate" into a forged
signature rendering as VÁLIDO.

The anchor is written all the same, and the suite uses it: INDETERMINATE is also what a malformed
file returns, so without checking that this one reaches VALID against its own authority the bundle
check would pass on garbage. The library may be called with anchors from tests, where nothing
ships.

Nothing here is anybody's. The key is generated on the spot and the common name says so.

Generated on each run rather than committed, for a plainer reason than the size of a binary in
git: a certificate has a validity window. A file checked in today would start failing CI a year
from now, on a commit that changed nothing, and the message would be about a signature rather
than about a clock.

It lives in tools/ with the storybook and the samples, outside src/, so it cannot be packaged and
cannot be imported by the app: ``packages.find`` only looks in src/, and a test holds the rule.

    uv run python -m tools.verify_fixture <directorio>

writes ``firmado.pdf`` and ``ca.pem`` there.
"""

from __future__ import annotations

import datetime
import io
import sys
from pathlib import Path

from asn1crypto import keys as asn1keys
from asn1crypto import x509 as asn1x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pyhanko.pdf_utils.generic import ArrayObject, NumberObject, StreamObject
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.writer import PageObject, PdfFileWriter
from pyhanko.sign.signers import PdfSignatureMetadata, SimpleSigner, sign_pdf
from pyhanko_certvalidator.registry import SimpleCertificateStore

# Said in the certificate itself, so anybody who opens the fixture reads what it is before
# wondering whose signature they are looking at.
COMMON_NAME = "FIXTURE SINTETICA DE PRUEBA, NO ES UNA PERSONA"


def _self_signed():
    """A key and its certificate, both made here and kept nowhere."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, COMMON_NAME)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=True, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=False,
            crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _signed_pdf(key, cert) -> bytes:
    """A one page PDF carrying one signature, built in memory."""
    writer = PdfFileWriter()
    contents = writer.add_object(StreamObject(stream_data=b""))
    writer.insert_page(PageObject(
        contents=contents,
        media_box=ArrayObject([NumberObject(n) for n in (0, 0, 200, 200)]),
    ))
    blank = io.BytesIO()
    writer.write(blank)
    blank.seek(0)

    signer = SimpleSigner(
        signing_cert=asn1x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER)),
        signing_key=asn1keys.PrivateKeyInfo.load(key.private_bytes(
            serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())),
        cert_registry=SimpleCertificateStore(),
    )
    signed = io.BytesIO()
    sign_pdf(IncrementalPdfFileWriter(blank), PdfSignatureMetadata(field_name="Sig1"),
             signer=signer, output=signed)
    return signed.getvalue()


def write(directory: Path) -> tuple[Path, Path]:
    """Put the pair in ``directory`` and return (pdf, ca)."""
    directory.mkdir(parents=True, exist_ok=True)
    key, cert = _self_signed()
    pdf = directory / "firmado.pdf"
    ca = directory / "ca.pem"
    pdf.write_bytes(_signed_pdf(key, cert))
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return pdf, ca


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: python -m tools.verify_fixture <directorio>", file=sys.stderr)
        return 2
    pdf, ca = write(Path(sys.argv[1]))
    print(f"fixture: {pdf} ({pdf.stat().st_size} bytes), anclas en {ca}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
