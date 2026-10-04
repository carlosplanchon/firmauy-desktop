# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Bridge to the firmauy core.

Every function here calls the firmauy public API (firmauy.api) in-process, so a frozen build
bundles firmauy and needs no `firmauy` on PATH. Signing goes through firmauy.api.sign, which
auto-detects the input: a PDF comes back as a signed PDF (PAdES), an XML as a signed XML
(XAdES), anything else as a detached .p7s (CAdES). Reading the cédula (identity and photo) is
public card data and needs no PIN.

Two rules hold everywhere in this module. Nothing raises: every function catches and returns a
result object, so a view can render a failure instead of guarding every call. And every failure
carries both a Spanish message for the person and an ``error_kind`` tag for the code, so the UI
branches on a stable string rather than on the wording of a sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Generic, Optional, Sequence, TypeVar

from firmauy.api import (
    BatchSignCancelled,
    BatchSignError,
    CardNotFoundError,
    CertificateNotFoundError,
    CertificateNotValidError,
    DetachedOriginalRequiredError,
    FirmaUYError,
    IncorrectPinError,
    OutputAccessControlError,
    OutputCommittedError,
    OutputExistsError,
    PdfAppearance,
    PostSignVerificationError,
    PinFormatError,
    PinLastTryError,
    PinLockedError,
    ReaderNotFoundError,
    SignAs,
    SigningKeyNotFoundError,
    TimestampDestinationRefusedError,
    TimestampError,
    TokenNotFoundError,
)
from firmauy.api import complete_ci as _api_complete_ci
from firmauy.api import fetch_cas as _api_fetch_cas
from firmauy.api import fetch_identity as _api_fetch_identity
from firmauy.api import fetch_photo as _api_fetch_photo
from firmauy.api import list_certs as _api_list_certs
from firmauy.api import list_readers as _api_list_readers
from firmauy.api import list_tokens as _api_list_tokens
from firmauy.api import output_path_for as _api_output_path_for
from firmauy.api import run_doctor as _api_run_doctor
from firmauy.api import sign as _api_sign
from firmauy.api import sign_files as _api_sign_files
from firmauy.api import validate_ci as _api_validate_ci
from firmauy.api import verify as _api_verify

from firmauy_desktop import activity

T = TypeVar("T")


class PinCancelled(Exception):
    """Raised by a pin_provider when the user dismisses the PIN prompt.

    It travels up through firmauy's signing session (whose context managers still close the
    card connection on the way out) and is turned into a plain cancelled SignResult here.
    """


# --- results ----------------------------------------------------------------

@dataclass
class Result(Generic[T]):
    """The envelope for the read-only calls, which all have the same shape."""

    ok: bool
    value: Optional[T] = None
    error: Optional[str] = None
    error_kind: str = ""


@dataclass
class SignResult:
    ok: bool
    output_path: str | None
    detail: str
    error_kind: str = ""
    kind: str = ""                # pades / xades / cades: what auto-detection produced
    backend: str = ""             # native / pkcs11
    signer: str = ""
    issuer: str = ""
    certificate_serial: str = ""
    verified: bool = False        # the fresh signature was re-read and checked
    conflict_path: str = ""       # on error_kind "output_exists", the file in the way
    # output_path is set on failure only for error_kind "output_committed", where the signature
    # is written and complete and its permissions are not.


@dataclass
class SignedItem:
    """One file's place in a batch."""

    path: str
    output_path: str = ""
    # pending / signed / warned / failed. "warned" is signed and on disk with something left to
    # do, which firmauy 1.14.0 made reachable: the signature is committed and its permissions are
    # not what they should be. Calling that "failed" told somebody a document did not exist while
    # it sat there, complete, and the obvious response to that is to sign it a second time.
    status: str = "pending"
    detail: str = ""


@dataclass
class BatchSignResult:
    ok: bool
    items: list = field(default_factory=list)   # one per input, in the order given
    error: str = ""
    error_kind: str = ""
    conflict_path: str = ""

    @property
    def signed(self) -> int:
        """How many outputs exist. A warned one is signed: only its permissions are pending."""
        return sum(1 for item in self.items if item.status in ("signed", "warned"))


@dataclass
class BatchPreflight:
    """What can be signed, and what has to be decided first.

    Everything here is checked before the card is touched, so the most likely mid-batch failure
    becomes a question asked before the PIN rather than a signature that stops halfway.
    """

    ready: list = field(default_factory=list)      # paths that can go straight through
    conflicts: list = field(default_factory=list)  # (input_path, existing_output_path)
    problems: list = field(default_factory=list)   # (input_path, why)

    @property
    def total(self) -> int:
        return len(self.ready) + len(self.conflicts) + len(self.problems)


@dataclass
class Party:
    """A signer or an issuer, as their certificate spells them out."""

    common_name: str = ""
    serial_number: str = ""       # for a signer, the cédula number the certificate carries
    organization: str = ""
    country: str = ""
    certificate_serial: str = ""


@dataclass
class Check:
    """One verification check. Rendered generically: never switch on the name.

    The set differs per format (a PDF yields 4 to 6, a detached CMS 3, a XAdES up to 10) and
    firmauy is free to add more.
    """

    name: str
    ok: bool
    detail: str = ""


@dataclass
class Timestamp:
    """When the signature existed, according to an RFC 3161 token inside the file.

    A separate question from whether the signature is valid, and worth keeping separate: a
    document can carry a sound signature and a broken timestamp.

    ``trusted`` is three-valued and ``None`` is the usual answer, not an edge case. Validating a
    TSA's own chain needs trust anchors for that TSA, this app supplies none, so the chain is
    never looked at. ``False`` would be a different claim: looked at, and it did not reach a
    trusted root. Reporting the first as the second would be inventing a problem.
    """

    present: bool = False
    intact: bool | None = None    # the token's own signature is unbroken
    valid: bool | None = None     # ...and cryptographically correct
    trusted: bool | None = None   # None = the TSA chain was never evaluated
    gen_time: datetime | None = None
    tsa: str = ""                 # the TSA's common name, when the token names one
    detail: str = ""              # firmauy's English detail, for the technical fold

    @property
    def sound(self) -> bool:
        """The token itself holds up. Says nothing about who issued it."""
        return bool(self.intact and self.valid)


@dataclass
class Signature:
    indication: str               # VALID / INVALID / INDETERMINATE
    trusted: bool = False         # the chain reached the Uruguayan national root
    signer: Party = field(default_factory=Party)
    issuer: Party = field(default_factory=Party)
    checks: list = field(default_factory=list)
    # None when the file carries no timestamp, and also when firmauy is too old to report one.
    # Read this rather than parsing the check rows: their wording differs per format.
    timestamp: Timestamp | None = None


@dataclass
class VerifyResult:
    indication: str  # VALID / INVALID / INDETERMINATE, or "" on error
    signatures: list = field(default_factory=list)
    error: str | None = None
    error_kind: str = ""


@dataclass
class VerifiedItem:
    """One file's place in a batch verification."""

    path: str
    result: VerifyResult | None = None    # None until this file's turn came


@dataclass
class BatchVerifyResult:
    ok: bool
    items: list = field(default_factory=list)   # one VerifiedItem per input, in the order given
    error: str = ""
    error_kind: str = ""


@dataclass
class DoctorCheck:
    status: str  # PASS / FAIL / WARN
    name: str
    detail: str
    fix: str | None
    # firmauy marks a check whose detail can carry the cardholder's own data: some PKCS#11
    # modules use the holder's name as the token label. A check without the flag is treated as
    # sensitive, so an older firmauy costs detail rather than privacy.
    sensitive: bool = True


@dataclass
class DoctorResult:
    ok: bool
    checks: list = field(default_factory=list)
    error: str | None = None
    error_kind: str = ""


@dataclass
class Photo:
    """The cardholder's photo, described. The bytes live on ``Identity.photo``."""

    format: str = ""
    mime: str = ""
    width: int | None = None
    height: int | None = None
    size_bytes: int = 0
    sha256: str = ""


@dataclass
class Identity:
    """What the "Mi cédula" screen shows. Fields the card omits come back empty."""

    full_name: str = ""
    id_number: str = ""
    id_number_valid: bool | None = None   # arithmetic check digit, not an identity check
    birth_date: str = ""
    birthplace: str = ""
    nationality: str = ""
    document_number: str = ""             # the physical card's number, not the cédula number
    issue_date: str = ""
    expiry_date: str = ""
    photo: bytes | None = None            # raw JPEG, or None when the card has no photo
    photo_meta: Photo | None = None       # its dimensions and digest, when there is a photo


@dataclass
class IdentityResult:
    ok: bool
    identity: Identity | None = None
    error: str | None = None
    error_kind: str = ""


@dataclass
class Token:
    label: str = ""
    manufacturer: str = ""
    model: str = ""
    serial: str = ""


@dataclass
class Cert:
    id: str = ""
    subject_common_name: str = ""
    subject_serial_number: str = ""       # the holder's cédula number, as the certificate spells it
    issuer_common_name: str = ""
    certificate_serial: str = ""
    not_after: str = ""
    digital_signature: bool | None = None
    pem: str | None = None


@dataclass
class CaPaths:
    root_path: str = ""
    intermediate_path: str = ""
    cache_dir: str = ""


@dataclass
class CiResult:
    """One entry point for both cédula-number helpers, driven by what was typed."""

    message: str = ""
    ok: bool | None = None                # True consistent, False not, None just a hint
    completed: str = ""                   # the full number when it was completed from a body


# --- turning firmauy's failures into something a person and the code can use --

def _verification_failed(exc) -> str:
    """The three ways the post-sign self-check does not confirm a signature.

    They are one class with a field rather than one message, because the answers are opposite:
    one says delete this and sign again, and the other two say specifically not to. Collapsing
    them into a single sentence would leave the person to guess which one they got.
    """
    name = exc.path.name if exc.path is not None else "El archivo firmado"
    if exc.outcome == "failed":
        return (f"{name} se escribió pero no pasó su propia comprobación: la firma que se "
                "produjo no está íntegra. Borralo y firmá de nuevo.")
    if exc.outcome == "detached-mismatch":
        covers = exc.covers.name if getattr(exc, "covers", None) is not None else "el original"
        return (f"{name} no verifica contra {covers} tal como está ahora. O la firma no está "
                f"íntegra, o {covers} cambió después de firmarse, y esto no puede distinguir "
                f"cuál de las dos. Firmar de nuevo firmaría {covers} tal como está hoy.")
    return (f"{name} se escribió, pero la comprobación posterior no se pudo completar, así que "
            "no se sabe si la firma está bien o mal: pasalo por Verificar antes de usarlo. "
            "Firmar de nuevo solo le agregaría una segunda firma a un documento cuya primera "
            "nunca se miró.")


def _translate(exc: BaseException) -> str:
    """Map a firmauy failure to a sentence a person can act on. Falls back to the raw message."""
    return _known(exc) or _unrecognised(exc)


def _known(exc: BaseException) -> "str | None":
    """The app's own sentence for this failure, or None when it has none.

    Split out from _translate so that "does the app have a name for this" is a question that can
    be asked without producing the answer, which one caller needs: reading the cardholder photo
    drops its failure entirely rather than turning it into a sentence, so it has to decide
    whether to record a crash without anything to show. Deciding it there with its own test drifts
    from this one the first time a translation is added.

    Ordered specific first.
    """
    if isinstance(exc, IncorrectPinError):
        if exc.attempts_remaining == 1:
            # firmauy will not spend a card's last try, so the next signature from here is turned
            # away before the PIN. "Te queda 1 intento" on its own invites that retry.
            return ("PIN incorrecto. Te queda 1 intento antes de que se bloquee, y la app no lo "
                    "va a usar: para volver a firmar hay que desbloquear la cédula.")
        if exc.attempts_remaining is not None:
            return f"PIN incorrecto. Te quedan {exc.attempts_remaining} intentos."
        return "PIN incorrecto."
    if isinstance(exc, PinLockedError):
        return ("El PIN está bloqueado por demasiados intentos incorrectos. "
                "Hay que desbloquear la cédula antes de poder firmar.")
    if isinstance(exc, PinFormatError):
        return ("El PIN de la cédula tiene entre 4 y 8 dígitos, solo números, y el que se "
                "ingresó no. No se mandó a la tarjeta, así que no se gastó ningún intento.")
    if isinstance(exc, PinLastTryError):
        # "Como mucho": the direct path refuses at one try left or fewer, PKCS#11 at the last.
        # "No lo usó" rather than "no lo pidió": the direct path counts again right before
        # sending, so now and then this arrives after the prompt, with the PIN already typed.
        return ("A la cédula le queda como mucho un intento de PIN, y si falla se bloquea, así "
                "que la app no lo usó. Hay que desbloquearla antes de volver a firmar. No se "
                "gastó ningún intento.")
    if isinstance(exc, ReaderNotFoundError):
        return "No se encontró un lector de tarjetas. Conectalo e intentá de nuevo."
    if isinstance(exc, CardNotFoundError):
        return "No se detectó la cédula en el lector. Insertala e intentá de nuevo."
    if isinstance(exc, CertificateNotValidError):
        return ("El certificado de la cédula está fuera de su período de validez. "
                "Si venció, hay que renovar la cédula.")
    if isinstance(exc, CertificateNotFoundError):
        return "No se encontró el certificado de firma en la cédula."
    if isinstance(exc, SigningKeyNotFoundError):
        return "La cédula tiene el certificado pero no la clave de firma."
    if isinstance(exc, TokenNotFoundError):
        return ("El middleware PKCS#11 no ve la cédula. Revisá que esté insertada, o probá el "
                "modo directo en Ajustes.")
    if isinstance(exc, OutputExistsError):
        name = exc.path.name if exc.path is not None else "el archivo firmado"
        return f"Ya existe {name}. Movelo o renombralo si querés firmar de nuevo."
    if isinstance(exc, OutputCommittedError):
        name = exc.path.name if exc.path is not None else "El archivo firmado"
        return (f"{name} se firmó y quedó guardado, pero no se le pudieron poner los permisos "
                "que correspondían, así que por ahora solo lo podés leer vos. La firma está "
                "completa: lo que falta son los permisos, no otra firma.")
    if isinstance(exc, PostSignVerificationError):
        return _verification_failed(exc)
    if isinstance(exc, OutputAccessControlError):
        name = exc.path.name if exc.path is not None else "el archivo"
        return (f"No se pudo conservar quién puede leer {name}, así que no se escribió nada y "
                "el archivo que estaba quedó intacto. Suele pasar cuando pertenece a otro "
                "usuario o a otro grupo.")
    # Before its parent, and split by link_local: for a link-local address the box in Ajustes
    # changes nothing, and suggesting it would send somebody to a switch that cannot help.
    if isinstance(exc, TimestampDestinationRefusedError):
        tsa = f"La TSA de Ajustes ({exc.host})" if exc.host else "La TSA de Ajustes"
        if exc.link_local:
            return (f"{tsa} está en una dirección link-local, que la app no usa nunca: en ese "
                    "rango responden los servicios de metadatos de la nube, no una TSA. La firma "
                    "no se guardó. Revisá la URL de la TSA en Ajustes.")
        return (f"{tsa} está en tu red local, y la app solo se conecta a direcciones públicas "
                "salvo que se lo permitas. La firma no se guardó. Si esa TSA es tuya, marcá "
                "\"Permitir servidores de la red local\" en Ajustes.")
    # Unreachable, refused the request, answered something that is not a timestamp: firmauy's
    # message says which, and it is the one thing a report about it can carry.
    if isinstance(exc, TimestampError):
        return ("No se pudo obtener el sello de tiempo de la TSA de Ajustes, así que la firma no "
                "se guardó. Podés reintentar, revisar la URL o dejarla vacía para firmar sin "
                f"sello. Detalle técnico: {_raw(exc)}")
    if isinstance(exc, FileNotFoundError):
        return "No se encontró el archivo."
    if isinstance(exc, PermissionError):
        return "No hay permiso para escribir donde va el archivo firmado."
    if isinstance(exc, DetachedOriginalRequiredError):
        expected = getattr(exc, "expected", None)
        if expected is not None:
            return (f"Este .p7s está separado del archivo que firmó. "
                    f"Se buscó {expected.name} al lado y no está. ¿Cuál es?")
        return "Este .p7s está separado del archivo original. Hace falta indicar cuál firmó."
    # Matched on the message because cryptography raises a bare ValueError here, with no type to
    # branch on. Worth the exception to the rule: the only file the app ever asks a person to
    # supply by path is the TSA certificate in Ajustes, so pointing that field at the wrong file
    # is the likeliest way to reach this, and "Unable to load PEM file" in the middle of a Spanish
    # screen tells them nothing about which field to go fix.
    if isinstance(exc, ValueError) and "Unable to load PEM" in str(exc):
        return ("No se pudo leer el certificado de la TSA: el archivo elegido en Ajustes no es "
                "un PEM legible.")
    # The other bare ValueError a person can reach, worth the same exception: dropping a file
    # that is not signed at all is the most common wrong input Verificar sees, and the English
    # format list names things the person may not know they are missing.
    if isinstance(exc, ValueError) and "could not detect the signature type" in str(exc):
        return ("Esto no parece un archivo firmado: no es un PDF firmado, un XML firmado "
                "(XAdES) ni un .p7s.")
    # Everything above is a condition this app knows how to name. What is left is one it does
    # not, and handing over firmauy's English text on its own made the app look like it had
    # switched languages, with nothing to say it had run out of sentences. The detail stays,
    # because it is the only thing a bug report can carry and nothing here prints it anywhere
    # else, but it arrives labelled as what it is: a technical string, not a sentence written
    # for the person reading it. An exception carrying no message at all still names its class,
    # which beats a line ending in a colon.
    return None


def _unrecognised(exc: BaseException) -> str:
    """What the app says about a failure it has no sentence for, and where that is decided.

    Also the one place that notes such a failure in the activity record, which is why it is a
    function rather than the last line of _translate. Every function here catches and returns a
    result instead of raising, on purpose: a bug in the core must not take a screen down. The
    cost was that Task.run's ``except`` never saw those, so the record's crash entry, the whole
    point of which is unanticipated failures, could not fire for the most unanticipated failure
    there is. Somebody with the record switched on hit a genuine core bug and got a file with no
    trace of it.

    Recording it here rather than at the nine call sites keeps one definition of "the app ran
    out of sentences". Adding a translation above takes a failure out of this set the same day
    it stops being unrecognised, with nothing to keep in step by hand.

    What lands is the exception's class and this app's own frames, never the message: the record
    writes from a closed vocabulary and _raw(exc) is text from a library underneath, which can
    hold anything. So the file says which call broke and how, and the sentence on screen carries
    the detail for the person to paste.
    """
    activity.crash(exc)
    return f"Falló de una forma que la app no reconoce. Detalle técnico: {_raw(exc)}"


def _raw(exc: BaseException) -> str:
    return str(exc).strip() or type(exc).__name__


def _conflict(exc: BaseException) -> str:
    """The file in the way, and only when there is one in the way.

    Read off `.path`, which several errors now carry for entirely different reasons: an output
    that already exists, one that was written and needs its permissions repaired, one that failed
    its own check. Only the first is a conflict, and only the first should reach a dialog offering
    to overwrite. The others name a file that exists on purpose.
    """
    if not isinstance(exc, OutputExistsError):
        return ""
    return str(exc.path) if exc.path is not None else ""


def _kind(exc: BaseException) -> str:
    """A stable tag so the UI branches on code, not on the wording of a Spanish sentence."""
    if isinstance(exc, PinLockedError):
        return "pin_locked"
    if isinstance(exc, IncorrectPinError):
        return "pin"
    if isinstance(exc, PinFormatError):
        return "pin_format"
    if isinstance(exc, PinLastTryError):
        return "pin_last_try"
    if isinstance(exc, ReaderNotFoundError):
        return "reader"
    if isinstance(exc, CardNotFoundError):
        return "card"
    if isinstance(exc, TokenNotFoundError):
        return "token"
    if isinstance(exc, (CertificateNotValidError, CertificateNotFoundError,
                        SigningKeyNotFoundError)):
        return "cert"
    if isinstance(exc, OutputExistsError):
        return "output_exists"
    # The three below all leave the caller somewhere other than "nothing happened", and two of
    # them leave a file on disk. Without their own tags they fell through to the FirmaUYError
    # catch-all and came out as "card_other", which tells somebody to go look at their cédula
    # over a permission bit.
    if isinstance(exc, OutputCommittedError):
        return "output_committed"
    if isinstance(exc, PostSignVerificationError):
        return "verify_failed"
    if isinstance(exc, OutputAccessControlError):
        return "access_control"
    if isinstance(exc, DetachedOriginalRequiredError):
        return "needs_original"
    if isinstance(exc, TimestampDestinationRefusedError):
        return "tsa_destination_refused"
    if isinstance(exc, TimestampError):
        return "tsa_failed"
    if isinstance(exc, FileNotFoundError):
        return "not_found"
    if isinstance(exc, FirmaUYError):
        return "card_other"
    return "other"


def _call(fn: Callable[[], T]) -> Result[T]:
    """Run a read-only firmauy call and wrap whatever happens."""
    try:
        return Result(True, fn())
    except Exception as exc:
        return Result(False, None, _translate(exc), _kind(exc))


def _text(value) -> str:
    """Whatever firmauy handed over, as something a label can show.

    Bytes get decoded rather than str()'d. Some PKCS#11 modules return a token attribute as
    bytes even though firmauy annotates it as a string: the Gemalto middleware does exactly that
    for the serial, and str() on bytes yields the Python repr, so the screen would read
    ``b'66000034D0201077'``. NUL and space padding is part of the PKCS#11 attribute format, not
    part of the value.
    """
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace").replace("\x00", "").strip()
    return str(value).strip()


# --- signing ----------------------------------------------------------------

def pin_shape(pin: str) -> str:
    """Whether a cédula could take ``pin``: "ok", or "empty", "short", "long" or "not_digits".

    The line firmauy draws before anything reaches the card, 4 to 8 of the digits 0-9, asked
    here so the PIN dialog can say what is wrong while the PIN is being typed. Nothing is lost
    either way, since firmauy refuses the same PIN at no cost, but its refusal came back after
    the signature had started, as an error to dismiss and a whole new attempt.

    Never stricter than firmauy, and a test holds the two to the same answers: a PIN the app
    turned away and firmauy would have sent is a card nobody could sign with from here.
    """
    if not pin:
        return "empty"
    # isascii() beside isdigit(), as in ci_digits and in firmauy: '٤' and '④' pass isdigit().
    if not (pin.isascii() and pin.isdigit()):
        return "not_digits"
    if len(pin) < 4:
        return "short"
    if len(pin) > 8:
        return "long"
    return "ok"


def _stamp_problem(exc: BaseException) -> str:
    """A stamp setting firmauy refuses, said in Spanish and pointing at where to change it.

    Reached before the card is touched, which is the whole reason PdfAppearance validates when it
    is built: a mistyped image path should not cost one of the cédula's PIN tries.
    """
    if isinstance(exc, FileNotFoundError):
        return ("No se encontró la imagen de la estampa. La ruta está en Ajustes; con el campo "
                "vacío, la firma va sin imagen.")
    # Not reachable from the dialog, whose combo and spin box cannot produce a bad value, nor from
    # a stored file, which settings.load() sanitises. A hand-edited store still lands here.
    return "La estampa de la firma tiene un ajuste que firmauy no acepta. Se arregla desde Ajustes."


def _appearance(stamp):
    """The stamp settings as firmauy's object. Raises, and both callers turn that into a result."""
    return PdfAppearance(**stamp) if stamp else None


def sign_file(path: str, pin: Optional[str] = None, *,
              pin_provider: Optional[Callable[[], str]] = None,
              sign_as: str = "auto",
              output: Optional[str] = None,
              reason: Optional[str] = None,
              location: Optional[str] = None,
              overwrite: bool = False,
              native: bool = True,
              reader: Optional[str] = None,
              pkcs11_lib: Optional[str] = None,
              tsa_url: Optional[str] = None,
              allow_private_network: bool = False,
              verify: bool = False,
              stamp: Optional[dict] = None) -> SignResult:
    """Sign ``path`` with the cédula via firmauy.api.sign, in-process (no subprocess).

    The signature type is auto-detected: a PDF produces a signed PDF (PAdES), an XML a signed
    XML (XAdES), anything else a detached ``.p7s`` (CAdES).

    Pass the PIN as ``pin``, or as a ``pin_provider`` callback that firmauy calls only once the
    reader, card and certificate check out, so the app can prompt for the PIN when it is
    actually needed (and never when the setup is broken). Either way the PIN stays in this
    process's memory, never in a subprocess argv or pipe.

    ``reader``, ``pkcs11_lib``, ``tsa_url``, ``allow_private_network`` and ``verify`` come from
    the app's settings, through ``settings.sign_kwargs``. ``tsa_url`` is the only one that touches
    the network, and ``allow_private_network`` lets it reach a TSA on a private one. ``sign_as``,
    ``output``, ``reason`` and ``location`` are per-document choices from the screen;
    ``reason`` and ``location`` only mean anything when the resolved type is a PDF.
    """
    try:
        # Coerced here rather than let through, so a bad combo value comes back as a Spanish
        # message instead of a raw English ValueError from deep inside firmauy.
        SignAs(sign_as)
    except ValueError:
        return SignResult(False, None, f"Tipo de firma desconocido: {sign_as}", "other")

    try:
        appearance = _appearance(stamp)
    except (ValueError, FileNotFoundError) as exc:
        return SignResult(False, None, _stamp_problem(exc), "stamp")

    # The record never learns which document this is, only its shape. That is the whole rule:
    # settings.py refuses a recent-files list for the same reason, and a log with one would be
    # that list under another name.
    activity.event("firma", sign_as=sign_as, backend="native" if native else "pkcs11",
                   verify=verify, stamped=bool(tsa_url))
    try:
        report = _api_sign(path, pin, pin_provider=pin_provider, sign_as=sign_as,
                           output=output, reason=reason, location=location,
                           overwrite=overwrite, native=native, reader=reader,
                           pkcs11_lib=pkcs11_lib, tsa_url=tsa_url,
                           allow_private_network=allow_private_network, verify=verify,
                           appearance=appearance)
    except PinCancelled:
        activity.event("firma cancelada")
        return SignResult(False, None, "Firma cancelada.", "cancelled")
    except Exception as exc:
        activity.event("firma falló", error_kind=_kind(exc))
        # ok=False with an output_path is not a contradiction, it is the honest shape of the one
        # failure that leaves a file behind: the signature is written and complete, and only its
        # permissions are not what they should be. Handing back None would say no file exists.
        written = (str(exc.path) if isinstance(exc, OutputCommittedError) and exc.path
                   else None)
        return SignResult(False, written, _translate(exc), _kind(exc),
                          conflict_path=_conflict(exc))

    activity.event("firma lista", kind=_text(report.kind), backend=_text(report.backend),
                   verified=bool(report.verified))
    written = str(report.output_path)
    return SignResult(
        True, written, written,
        kind=_text(report.kind), backend=_text(report.backend),
        signer=_text(report.signer), issuer=_text(report.issuer),
        certificate_serial=_text(report.certificate_serial),
        verified=bool(report.verified),
    )


def output_path_for(path: str, *, sign_as: str = "auto",
                    output_dir: Optional[str] = None) -> Result[str]:
    """Where the signature for ``path`` will actually be written.

    The views may not import firmauy, and they must not reimplement this rule either. Working it
    out by hand is how "Guardar en" came to send firmauy the input's own name: a detached
    signature for ``doc.bin`` was written as ``doc.bin`` instead of ``doc.bin.p7s``, and forcing
    CAdES on ``contrato.pdf`` put CMS inside a file still called ``.pdf``.

    Reads the file to detect its type when ``sign_as`` is "auto", so the file has to be there.
    """
    return _call(lambda: str(_api_output_path_for(path, sign_as=sign_as, output_dir=output_dir)))


def preflight_batch(paths: Sequence[str], *, sign_as: str = "auto",
                    output_dir: Optional[str] = None) -> BatchPreflight:
    """Sort a batch into what can go straight through, what collides, and what is broken.

    Runs before the card is touched, so the likeliest mid-batch failure (an output that is
    already there) becomes a question asked before the PIN instead of a batch that stops
    halfway. Local stats plus a small read per file to detect its type, no card and no network.

    Never raises: a file it cannot make sense of lands in ``problems`` with a reason.
    """
    ready, conflicts, problems = [], [], []
    seen_outputs: dict[str, str] = {}
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            problems.append((str(path), "no existe"))
            continue
        if path.is_dir():
            problems.append((str(path), "es una carpeta"))
            continue
        try:
            out = _api_output_path_for(path, sign_as=sign_as, output_dir=output_dir)
        except Exception as exc:
            problems.append((str(path), _translate(exc)))
            continue

        earlier = seen_outputs.get(str(out))
        if earlier is not None:
            # Two inputs landing on one output would silently overwrite each other mid-batch.
            problems.append((str(path), f"chocaría con {Path(earlier).name}"))
            continue
        seen_outputs[str(out)] = str(path)

        if out.exists():
            conflicts.append((str(path), str(out)))
        else:
            ready.append(str(path))
    return BatchPreflight(ready, conflicts, problems)


def sign_batch(paths: Sequence[str], *,
               pin_provider: Callable[[], str],
               progress: Optional[Callable[[SignedItem], None]] = None,
               should_continue: Optional[Callable[[], bool]] = None,
               sign_as: str = "auto",
               output_dir: Optional[str] = None,
               reason: Optional[str] = None,
               location: Optional[str] = None,
               overwrite: bool = False,
               native: bool = True,
               reader: Optional[str] = None,
               pkcs11_lib: Optional[str] = None,
               tsa_url: Optional[str] = None,
               allow_private_network: bool = False,
               verify: bool = False,
               stamp: Optional[dict] = None) -> BatchSignResult:
    """Sign several files in one card session, so the PIN is checked once for the whole batch.

    ``progress`` is called with a :class:`SignedItem` after each output is written, on the
    worker thread. Its argument is a single object rather than firmauy's ``(index, src, out)``
    triple, so a Qt signal can carry it.

    ``should_continue`` is asked before each file whether to keep going, which is how a Cancel
    button works. It is only consulted between files, so a stop takes effect after the one being
    signed, and a batch of a single large document cannot be interrupted at all.

    On a failure or a cancellation part-way through, everything already signed comes back with
    the reason and the file it stopped at. Those outputs stay on disk: each one is a complete
    signature, written in full, and saying "2 of 7 were signed" is what the person needs to hear.

    Complete is not the same as verified, and this says the first. The self-check runs only when
    ``verify`` asks for it, which is off unless the setting turns it on, so what is promised here
    is that the output was produced, never that it was read back and found intact. `SignReport`
    carries that separately, per file.
    """
    items = [SignedItem(str(p)) for p in paths]
    by_path = {item.path: item for item in items}

    try:
        appearance = _appearance(stamp)
    except (ValueError, FileNotFoundError) as exc:
        # Before the card, so a mistyped image path costs nothing and no file is signed.
        return BatchSignResult(False, items, _stamp_problem(exc), "stamp")

    def relay(index: int, src, out) -> None:
        item = by_path.get(str(src))
        if item is not None:
            item.output_path = str(out)
            item.status = "signed"
            if progress is not None:
                progress(item)

    activity.event("lote", total=len(items), sign_as=sign_as,
                   backend="native" if native else "pkcs11", verify=verify)
    try:
        _api_sign_files(
            [item.path for item in items], pin_provider=pin_provider, progress=relay,
            should_continue=should_continue,
            sign_as=sign_as, output_dir=output_dir, reason=reason, location=location,
            overwrite=overwrite, native=native, reader=reader, pkcs11_lib=pkcs11_lib,
            tsa_url=tsa_url, allow_private_network=allow_private_network, verify=verify,
            appearance=appearance,
        )
    except (PinCancelled, BatchSignCancelled):
        # Both are the person deciding to stop, not something going wrong, so neither carries an
        # error message. Whatever was signed before it is in `items` already.
        return BatchSignResult(False, items, "", "cancelled")
    except BatchSignError as exc:
        cause = exc.__cause__ or exc
        # Translated once, for the row and for the batch alike. Twice recorded the same failure
        # in the activity record twice, because the crash entry lives where the app decides it
        # has run out of sentences, and asking that question is what produces the answer.
        message, kind = _translate(cause), _kind(cause)
        if 0 <= exc.failed_index < len(items):
            # firmauy: "the file at failed_index can itself appear in completed", for the two
            # failures that land after the output is finished. Reporting either as failed would
            # name a document that does not exist while it sits there complete, and the obvious
            # response to that is to sign it a second time.
            item = items[exc.failed_index]
            if isinstance(cause, OutputCommittedError):
                # Written too, only with the wrong mode, and firmauy calls progress for it, so
                # `relay` has already marked it signed with its output path. Checked before the
                # callback, because a callback can raise on this one as well and the permissions
                # still need repairing.
                item.status, item.detail = "warned", message
            elif cause is not exc.callback_error:
                item.status, item.detail = "failed", message
            # Otherwise the only thing that broke was this app's own progress callback, after the
            # output had been written in full. Failing to show progress cannot unwrite a file, so
            # `relay`'s answer stands.

        if cause is exc.callback_error:
            # Not a signing failure at all. Surfacing the callback's own message would show a
            # sentence about a deleted Qt object, which is true and useless to the person.
            done = sum(1 for item in items if item.status in ("signed", "warned"))
            # "quedó guardado", not "quedó bien": the self-check is off unless the setting asks
            # for it, so what is known here is that the file was written, not that it verifies.
            written = ("Se firmó 1 archivo y quedó guardado" if done == 1
                       else f"Se firmaron {done} archivos y quedaron guardados")
            message = (f"{written}, pero la app falló al mostrar el avance, así que el lote se "
                       "detuvo ahí y el resto no se firmó.")
            kind = "callback_failed"
        activity.event("lote se detuvo", error_kind=kind,
                       firmados=sum(1 for i in items if i.status in ("signed", "warned")))
        return BatchSignResult(False, items, message, kind, _conflict(cause))
    except Exception as exc:
        # The PIN is asked once, while the session opens and before the first file, so a refusal
        # arrives here rather than inside a BatchSignError.
        return BatchSignResult(False, items, _translate(exc), _kind(exc), _conflict(exc))

    activity.event("lote listo", firmados=sum(1 for i in items if i.status == "signed"))
    return BatchSignResult(True, items)


# --- verifying --------------------------------------------------------------

def verify_file(path: str, *, original: Optional[str] = None,
                check_revocation: bool = False,
                tsa_ca: Optional[str] = None,
                allow_private_network: bool = False) -> VerifyResult:
    """Verify a signed file via the firmauy public API, in-process (no subprocess).

    No PIN or card needed. ``original`` is the file a detached ``.p7s`` signs, for when it did
    not travel next to it. ``check_revocation`` is the only network I/O here: it fetches CRLs
    and OCSP responses, hard-fails, and can hang, so it is off unless the user asked for it.
    ``allow_private_network`` lets those fetches reach a private address, and the addresses come
    from the certificates in the file, which is why it is off unless Ajustes says otherwise.

    ``tsa_ca`` is a PEM bundle of timestamping authorities. None leaves a signature timestamp
    reported as present and unvalidated, which is what this app did until the option existed:
    the date was shown as something a stranger asserted, and it stayed that way even when the
    anchor that would have settled it was sitting on the machine. With it, ``Timestamp.trusted``
    becomes True or False rather than None, and a token that validates also moves the moment the
    signer's own certificate is judged at, so a signature outlives the certificate that made it.
    """
    result = _verify_one(path, original=original, check_revocation=check_revocation,
                         tsa_ca=tsa_ca, allow_private_network=allow_private_network)
    if result.error:
        activity.event("verificación falló", error_kind=result.error_kind)
    else:
        activity.event("verificación lista", indication=result.indication,
                       firmas=len(result.signatures), revocation=check_revocation)
    return result


def _verify_one(path: str, *, original: Optional[str] = None,
                check_revocation: bool = False,
                tsa_ca: Optional[str] = None,
                allow_private_network: bool = False) -> VerifyResult:
    """One file's verification, with nothing said to the activity record.

    Split from verify_file so the batch can share it: the record hears one line per thing a
    person asked for, and a batch of two hundred files is one ask, not two hundred.
    """
    try:
        report = _api_verify(path, original=original, check_revocation=check_revocation,
                             tsa_ca=tsa_ca, allow_private_network=allow_private_network)
    except Exception as exc:
        return VerifyResult("", error=_translate(exc), error_kind=_kind(exc))

    signatures = [
        Signature(
            indication=_text(s.indication),
            trusted=bool(s.trusted),
            signer=_party(s.signer),
            issuer=_party(s.issuer),
            checks=[Check(_text(c.name), bool(c.ok), _text(c.detail)) for c in s.checks],
            timestamp=_timestamp(getattr(s, "timestamp", None)),
        )
        for s in report.signatures
    ]
    return VerifyResult(report.indication, signatures)


def verify_batch(paths: Sequence[str], *,
                 progress: Optional[Callable[[VerifiedItem], None]] = None,
                 should_continue: Optional[Callable[[], bool]] = None,
                 check_revocation: bool = False,
                 tsa_ca: Optional[str] = None,
                 allow_private_network: bool = False) -> BatchVerifyResult:
    """Verify several files, one at a time, in the order given. No card, no PIN.

    Offline unless ``check_revocation``. A file that cannot be verified is an answer on its
    row (its ``VerifyResult`` carries the error), never a stop. ``should_continue`` is asked
    before each file, so a stop finishes nothing halfway. ``progress`` receives each
    ``VerifiedItem`` the moment its result exists, which is what lets a screen keep the
    verdicts already delivered even if it stops waiting for the rest. The record hears two
    lines per batch, not two per file.
    """
    items = [VerifiedItem(str(p)) for p in paths]
    activity.event("lote a verificar", total=len(items), revocation=check_revocation)

    def close(ok: bool, error_kind: str = "") -> BatchVerifyResult:
        answered = [item for item in items if item.result is not None]
        fallos = sum(1 for item in answered if item.result.error)
        if error_kind:
            activity.event("lote verificado", n=len(answered), fallos=fallos,
                           error_kind=error_kind)
        else:
            activity.event("lote verificado", n=len(answered), fallos=fallos)
        return BatchVerifyResult(ok, items, "", error_kind)

    try:
        for item in items:
            if should_continue is not None and not should_continue():
                return close(False, "cancelled")
            item.result = _verify_one(item.path, check_revocation=check_revocation,
                                      tsa_ca=tsa_ca, allow_private_network=allow_private_network)
            if progress is not None:
                progress(item)
    except Exception as exc:
        # _verify_one never raises, so only this app's own progress callback can land here.
        return BatchVerifyResult(False, items, _translate(exc), _kind(exc))
    return close(True)


def _party(fields: dict) -> Party:
    """firmauy hands these as a name_fields dict; missing keys are simply absent."""
    return Party(
        common_name=_text(fields.get("common_name")),
        serial_number=_text(fields.get("serial_number")),
        organization=_text(fields.get("organization")),
        country=_text(fields.get("country")),
        certificate_serial=_text(fields.get("certificate_serial")),
    )


def _timestamp(info) -> Optional[Timestamp]:
    """firmauy's TimestampInfo, or None when there is no timestamp to report.

    ``getattr`` rather than a plain attribute read, even though pyproject now floors firmauy at
    1.12.0, which is the version that started reporting this. The floor is what resolves at
    install time and not what a person is running: an editable checkout, a distro package or a
    frozen bundle can all put an older core underneath. Degrading to no timestamp row costs one
    row and nothing else, which is the same bargain the ``sensitive`` flag on a doctor check
    already makes.

    The three-valued fields are copied, never coerced. ``bool(None)`` here would turn "never
    evaluated" into "evaluated and failed", which is exactly the distinction firmauy went to the
    trouble of restoring.
    """
    if info is None or not getattr(info, "present", False):
        return None
    return Timestamp(
        present=True,
        intact=getattr(info, "intact", None),
        valid=getattr(info, "valid", None),
        trusted=getattr(info, "trusted", None),
        gen_time=getattr(info, "gen_time", None),
        tsa=_text(getattr(info, "tsa_common_name", "")),
        detail=_text(getattr(info, "detail", "")),
    )


# --- diagnosing -------------------------------------------------------------

def run_doctor(*, native: bool = True, reader: Optional[str] = None,
               pkcs11_lib: Optional[str] = None) -> DoctorResult:
    """Diagnose the signing environment via the firmauy public API, in-process. No PIN needed.

    Note that firmauy's native and PKCS#11 branches return early on a failing check, so the list
    can be shorter than expected. Never assume a fixed number of rows.
    """
    try:
        report = _api_run_doctor(native=native, reader=reader, pkcs11_lib=pkcs11_lib)
    except Exception as exc:
        activity.event("diagnóstico falló", error_kind=_kind(exc))
        return DoctorResult(False, error=_translate(exc), error_kind=_kind(exc))

    checks = [
        DoctorCheck(c.status, c.name, c.detail, c.fix, getattr(c, "sensitive", True))
        for c in report.checks
    ]
    # Only the tally. A check's detail can be the token label, which some PKCS#11 modules
    # set to the holder's own name, and Diagnóstico already redacts it for the clipboard.
    activity.event("diagnóstico", ok=report.ok,
                   fallos=sum(1 for c in checks if c.status == "FAIL"))
    return DoctorResult(report.ok, checks)


# The lines firmauy can send while fetching the national CAs, glossed like its errors: the two
# shapes the app can meet (a retry, and the fall back to the pinned mirror) are translated, and
# an unrecognised line passes through in English rather than disappearing. A smooth run says
# nothing at all, so these only ever narrate network trouble.
_CA_RETRY = re.compile(r"^(?P<host>\S+): attempt (?P<n>\d+)/(?P<total>\d+) failed "
                       r"\((?P<err>[^)]*)\); retrying in (?P<delay>[\d.]+)s…$")
_CA_FALLBACK = re.compile(r"^(?P<host>\S+) unavailable \((?P<err>[^)]*)\); "
                          r"falling back to (?P<next>\S+)…$")


def _gloss_net_error(err: str) -> str:
    return "no respondió a tiempo" if err == "timed out" else err


def _gloss_ca_progress(line: str) -> str:
    hit = _CA_RETRY.match(line)
    if hit:
        return (f"{hit['host']}: intento {hit['n']} de {hit['total']} falló "
                f"({_gloss_net_error(hit['err'])}); reintentando en {hit['delay']}s...")
    hit = _CA_FALLBACK.match(line)
    if hit:
        return (f"{hit['host']} no responde ({_gloss_net_error(hit['err'])}); "
                f"probando con {hit['next']}...")
    return line


def refresh_cas(*, progress: Optional[Callable[[str], None]] = None) -> Result[CaPaths]:
    """Re-download the national CA certificates into the per-user cache. Uses the network.

    Optional: verification already works offline against the anchors bundled with firmauy. This
    is the repair action for the "bundled national CA certificates" check, and it matters in a
    frozen build, where firmauy prefers the cached copies over the ones baked into the bundle.
    """
    def work() -> CaPaths:
        relay = None if progress is None else (
            lambda line: progress(_gloss_ca_progress(line)))
        bundle = _api_fetch_cas(progress=relay)
        return CaPaths(str(bundle.root_path), str(bundle.intermediate_path),
                       str(bundle.cache_dir))

    return _call(work)


# --- reading the cédula (no PIN) --------------------------------------------

def _full_name(person) -> str:
    """Given names first, then both surnames, the way a cédula reads."""
    parts = [person.given_names, person.lastnames, person.second_lastname]
    return " ".join(p.strip() for p in parts if p and p.strip())


def read_identity(*, reader: Optional[str] = None) -> IdentityResult:
    """Read the cardholder's data and photo from the cédula over PC/SC. No PIN needed.

    The two reads are separate card conversations, so a card without a photo (or a photo that
    cannot be read) still yields the biographic data. This data is personal: it stays on this
    machine, and the app never writes it anywhere the user did not ask for.
    """
    try:
        person = _api_fetch_identity(reader=reader)
    except Exception as exc:
        return IdentityResult(False, error=_translate(exc), error_kind=_kind(exc))

    photo, photo_meta = None, None
    try:
        report = _api_fetch_photo(reader=reader)
        photo = report.data
        photo_meta = Photo(
            format=_text(report.format), mime=_text(report.mime),
            width=report.width, height=report.height,
            size_bytes=report.size_bytes, sha256=_text(report.sha256),
        )
    except Exception as exc:
        # The biographic data is worth showing even when the photo cannot be read. Mapping the
        # metadata is inside the try for the same reason: a field disappearing from firmauy's
        # PhotoReport should cost the metadata line, not the whole screen.
        #
        # This is the one place that drops a failure entirely instead of turning it into a
        # sentence, so it is also the one the record cannot learn about any other way. A card
        # with no photo on it is a condition and says nothing here. Anything the app has no name
        # for is a bug that leaves no trace at all, which is exactly what the crash entry is for.
        if _known(exc) is None:
            _unrecognised(exc)

    return IdentityResult(True, Identity(
        full_name=_full_name(person),
        id_number=person.id_number or "",
        id_number_valid=person.id_number_check_digit_valid,
        birth_date=person.birth_date or "",
        birthplace=person.birthplace or "",
        nationality=person.nationality or "",
        document_number=person.document_number or "",
        issue_date=person.issue_date or "",
        expiry_date=person.expiry_date or "",
        photo=photo,
        photo_meta=photo_meta,
    ))


# --- introspection ----------------------------------------------------------

def list_readers() -> Result[list[str]]:
    """The PC/SC reader names, which are exactly what the ``reader`` setting accepts."""
    return _call(lambda: list(_api_list_readers()))


def list_tokens(*, pkcs11_lib: Optional[str] = None) -> Result[list[Token]]:
    """The tokens a PKCS#11 module exposes. Empty when no card is in the reader."""
    def work() -> list[Token]:
        return [
            Token(_text(t.label), _text(t.manufacturer), _text(t.model), _text(t.serial))
            for t in _api_list_tokens(pkcs11_lib=pkcs11_lib)
        ]

    return _call(work)


def list_certs(*, pkcs11_lib: Optional[str] = None,
               include_pem: bool = False) -> Result[list[Cert]]:
    """The certificates on the token. Needs the card, but no PIN.

    firmauy's ``pin`` argument is deliberately not exposed: cédula tokens do not hide their
    certificate list behind a login, and asking for a PIN to read public data would spend the
    card's limited tries for nothing.
    """
    def work() -> list[Cert]:
        return [
            Cert(
                id=_text(c.id),
                subject_common_name=_text(c.subject.get("common_name")),
                subject_serial_number=_text(c.subject.get("serial_number")),
                issuer_common_name=_text(c.issuer.get("common_name")),
                certificate_serial=_text(c.certificate_serial),
                not_after=_text(c.not_after),
                digital_signature=c.digital_signature,
                pem=c.pem,
            )
            for c in _api_list_certs(pkcs11_lib=pkcs11_lib, include_pem=include_pem)
        ]

    return _call(work)


# --- the cédula number (no card, no network) --------------------------------

def ci_digits(text: str) -> str:
    """The digits in ``text`` that a cédula number is written in: 0 to 9, and nothing else.

    Not ``str.isdigit``, which also says yes to '²', '٣' and '４'. The superscript raised out of
    int() inside firmauy and came back as a failure the app did not recognise, recorded as a
    crash, and the other two were checked as a cédula and answered in mixed scripts
    ("0000٣٤٥0"). firmauy's PIN check draws the same line, with isascii() beside isdigit().

    Public because the field on Mi cédula reduces what is typed by the same rule, and one
    definition is what keeps the field and its checker from drifting apart.
    """
    return "".join(ch for ch in text if ch.isascii() and ch.isdigit())


def check_ci(text: str) -> CiResult:
    """Validate or complete a cédula number, choosing by how much was typed.

    One entry point for both firmauy helpers, so a screen can be a single field with no button:
    eight digits are validated, one to seven are completed with their check digit, and anything
    else gets a hint. Never raises, so it is safe to call on every keystroke.

    This is arithmetic consistency, not an identity check. It catches typos, nothing more.
    """
    digits = ci_digits(text)
    if not digits:
        return CiResult()
    if len(digits) > 8:
        return CiResult("Una cédula tiene hasta 8 dígitos.")

    try:
        if len(digits) < 8:
            full = _api_complete_ci(digits)
            return CiResult(f"Con dígito verificador: {full}", completed=full)
        report = _api_validate_ci(digits)
    except Exception as exc:
        return CiResult(_translate(exc))

    if report.valid:
        return CiResult("El número es consistente.", ok=True)
    return CiResult(
        f"No es consistente: el dígito verificador debería ser {report.expected_check_digit}.",
        ok=False,
    )
