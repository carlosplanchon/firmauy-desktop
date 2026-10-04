# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""The Spanish the app says for firmauy's English vocabulary.

This is content, not part of the visual system: it is the wording somebody reads, and it belongs
next to the other things the app says rather than next to the colours it says them in. Nothing
here knows about Qt.

The one rule that matters: **no logic ever switches on a check name.** The set differs per format
(a PDF yields four to six, a detached CMS three, a XAdES up to ten) and firmauy is free to add
more, so every lookup here falls through to the raw English. A check added upstream degrades to
a sentence nobody translated yet, never to a row that silently disappears.
"""

from __future__ import annotations

import re
from datetime import timezone

INDICATION_LABEL = {
    "VALID": "VÁLIDO",
    "INVALID": "INVÁLIDO",
    "INDETERMINATE": "INDETERMINADO",
}

CHECK_LABEL = {
    # PDF and detached CMS
    "signature intact (covered bytes unmodified)": "La firma está intacta (no se modificó lo firmado)",
    "signature intact (signed bytes unmodified)": "La firma está intacta (no se modificó lo firmado)",
    "signature cryptographically valid": "La firma es criptográficamente válida",
    "coverage (whole file)": "La firma cubre todo el archivo",
    "certificate chain to trusted root": "Cadena de certificados hasta una raíz de confianza",
    "signature present": "El archivo tiene una firma",
    "hybrid cross-reference sections: validated in relaxed mode":
        "Secciones de referencias cruzadas híbridas: validadas en modo relajado",
    # XAdES
    "signature structure": "Estructura de la firma",
    "signing certificate": "Certificado de firma",
    "document digest (reference)": "Huella del documento (referencia)",
    "signed-properties digest": "Huella de las propiedades firmadas",
    "SignedInfo signature (RSA-SHA256)": "Firma del SignedInfo (RSA-SHA256)",
    "SigningCertificate binding": "Vínculo con el certificado de firma",
    "signature timestamp present (XAdES-T, TSA not trust-validated)":
        "Tiene sello de tiempo (XAdES-T, sin validar la cadena de la TSA)",
    "signature timestamp (XAdES-T, TSA chain validated)":
        "Sello de tiempo (XAdES-T, cadena de la TSA validada)",
    # The same two for PDF and detached CMS, which firmauy started reporting in 1.12.0. It used
    # to drop the timestamp outcome entirely on those two paths, so a file with a broken token
    # came back with no row about it at all.
    "signature timestamp present (TSA not trust-validated)":
        "Tiene sello de tiempo (sin validar la cadena de la TSA)",
    "signature timestamp (TSA chain validated)":
        "Sello de tiempo (cadena de la TSA validada)",
    # doctor
    "firmauy": "firmauy",
    "pcscd running": "pcscd andando",
    # Windows has no pcscd. firmauy 1.21.0 asks the Smart Card service (SCardSvr) instead, in the
    # same position on the screen.
    "Smart Card service available": "Servicio de tarjeta inteligente disponible",
    "PC/SC reader detected": "Lector PC/SC detectado",
    "cédula detected": "Cédula detectada",
    "PKCS#11 module present": "Módulo PKCS#11 presente",
    "PKCS#11 module loads": "El módulo PKCS#11 carga",
    "cédula token detected": "Token de la cédula detectado",
    "bundled national CA certificates": "Certificados de las CA nacionales incluidos",
}


# The short English phrases firmauy puts in a check's *detail*, as opposed to its name. Read out
# of firmauy rather than guessed: these are the ones it actually emits.
#
# Same fall-through as everything else here, and for a stronger reason: a detail is free-form.
# Most of them are not prose at all (a version, a reader name, a module path) and must come
# through untouched, so this only speaks for the handful that are English sentences sitting in
# the middle of a Spanish screen.
CHECK_DETAIL = {
    # doctor: the complete set, read out of firmauy with an AST walk rather than by grepping.
    # A regex over part of the file is how "none found" got missed and then "corrected" out of
    # a fixture for being imaginary, which it was not.
    "installed but not running": "instalado pero no está corriendo",
    "not found": "no se encontró",
    "none found": "no se encontró ninguno",
    "no card found": "no hay ninguna tarjeta",
    "IAS applet selected": "applet IAS seleccionado",
    "root + intermediate loaded": "raíz e intermedia cargadas",
    "not loadable": "no se pudo cargar",
    "unknown": "desconocido",
    # verify
    "not trusted": "no es de confianza",
    "RFC 5280 path validated to trusted root": "cadena RFC 5280 validada hasta una raíz de confianza",
    "no enveloped reference": "no tiene referencia envuelta",
    "timestamp does not match the signature value": "el sello de tiempo no coincide con la firma",
    "timestamp token signature is invalid": "la firma del sello de tiempo no es válida",
    "TSA chain does not reach a trusted root":
        "la cadena de la TSA no llega a una raíz de confianza",
    # firmauy 1.13.0 dropped a generic "the timestamp token is broken" that PDF and CMS used to
    # send in place of the two specific reasons above, so the gloss for it went with it. Losing it
    # is the point: "está roto" tells a reader nothing they can act on, where the specific reasons
    # say whether the token itself failed or whether it is not this signature's token at all.
}


# The parenthesised half of a genTime detail. firmauy writes these as f-strings around a
# timestamp, so neither the whole detail nor its English half ever appears in the table above.
_GEN_TIME = re.compile(r"^genTime (\S+)(?: \((.*)\))?$")

_GEN_TIME_ASIDE = {
    "asserted by the TSA, not verified": "lo afirma la TSA, sin verificar",
    "trusted": "de confianza",
}


# What to do about a failing check. firmauy writes these for its command line, so this is not a
# translation: two of them name CLI flags that do not exist in a window, and one says to reinstall
# the package when the app has a button for exactly that job three rows below. The Spanish points
# at what a person using *this* app can actually press. Shell commands are kept verbatim, because
# a command is not prose.
CHECK_FIX = {
    "Start it: sudo systemctl enable --now pcscd":
        "Arrancalo: sudo systemctl enable --now pcscd",
    "Install the smart-card stack: sudo pacman -S pcsclite ccid":
        "Instalá el stack de tarjetas: sudo pacman -S pcsclite ccid",
    "Install the smart-card stack (sudo pacman -S pcsclite ccid) and start pcscd.":
        "Instalá el stack de tarjetas (sudo pacman -S pcsclite ccid) y arrancá pcscd.",
    # pcscd has its own check row directly above, with its own fix, so the fix here is only the
    # half the app cannot do or see for itself.
    "Connect a reader and make sure pcscd is running.":
        "Conectá un lector.",
    "Insert the cédula and check the reader connection / pcscd.":
        "Poné la cédula en el lector.",
    # Windows, from firmauy 1.21.0. Same reasoning as the two above: the service has its own row.
    "Insert the cédula and check the reader connection / Smart Card service.":
        "Poné la cédula en el lector.",
    "Connect the reader; Windows starts the Smart Card service (SCardSvr) on its own.":
        "Conectá el lector. Windows arranca solo el servicio de tarjeta inteligente (SCardSvr).",
    # Named as a Spanish Windows names them, since that is the screen somebody will be looking at.
    'Connect a reader and check that Windows lists it under "Smart card readers" in Device Manager.':
        'Conectá un lector y fijate que Windows lo muestre en "Lectores de tarjetas inteligentes", '
        "en el Administrador de dispositivos.",
    # --reader is a command-line flag. In here the reader is a dropdown at the top of this screen.
    "Insert the cédula, or pass --reader if you have more than one reader.":
        "Poné la cédula. Si tenés más de un lector, elegilo arriba.",
    "A card is present but did not answer as a cédula; check it is the right card.":
        "Hay una tarjeta en el lector pero no contesta como una cédula. Si es otra tarjeta, "
        "poné la cédula.",
    # --pkcs11-lib likewise: here the module is a field in Ajustes.
    "Install the middleware (Arch: yay -S cedula-uruguay-pkcs11), or pass --pkcs11-lib.":
        "Instalá el middleware (en Arch: yay -S cedula-uruguay-pkcs11), o poné la ruta del "
        "módulo en Ajustes.",
    "Install Thales Classic Client (the cédula middleware), or pass --pkcs11-lib.":
        "Instalá Thales Classic Client (el middleware de la cédula), o poné la ruta del módulo en "
        "Ajustes.",
    # Built rather than written: the 64-bit path follows the colon, and check_fix keeps it as it is.
    # Classic Client installs both copies, and the one under "Program Files (x86)" cannot load in
    # this app, which is 64-bit like the Python it was frozen from.
    "A 64-bit Python cannot load the 32-bit gclib.dll. Use the 64-bit one":
        "Esta app es de 64 bits y no puede cargar el gclib.dll de 32 bits. En Ajustes, poné el de "
        "64 bits",
    "The module is present but could not be initialised; check the middleware install.":
        "El módulo está pero no se pudo inicializar. Reinstalá el middleware, o probá el modo "
        "directo en Ajustes.",
    # firmauy travels inside this app, so "reinstall firmauy" is not something a person can do.
    # The button that refreshes those certificates is on this very screen.
    "The package install looks broken; reinstall firmauy.":
        "Probá actualizar los certificados acá abajo. Si sigue fallando, reinstalá la app.",
}

# The State validator, and what uploading there means. One sentence in one place, shared by
# every screen that points at the arbiter, so the claim cannot drift between them.
VALIDATOR_URL = "https://firma.gub.uy/"
VALIDATOR_NOTE = ("El árbitro que va a usar tu contraparte es firma.gub.uy, el validador del "
                  "Estado. Subirlo envía el documento a ese sitio.")
VALIDATOR_TOOLTIP = "Se abre en tu navegador. La app no sube nada por sí sola."


def check_fix(fix: str) -> str:
    """The Spanish for what to do about a failing check, or the text itself.

    A built fix gets the same treatment as a built detail: the English before the first ``": "``
    is glossed, and what follows, a module path, is kept verbatim.
    """
    if fix in CHECK_FIX:
        return CHECK_FIX[fix]
    prefix, colon, rest = fix.partition(": ")
    if colon and prefix in CHECK_FIX:
        return f"{CHECK_FIX[prefix]}: {rest}"
    return fix


def check_detail(detail: str) -> str:
    """The Spanish for a check's detail, or the detail itself.

    Untouched is the common case and the right default: a version, a reader name or a module
    path is not English, it is data, and translating it would be wrong.

    Some details are built rather than written: firmauy sends ``not found: /usr/lib/...`` as one
    f-string, so the English half never appears in any table. Those get their prefix glossed and
    keep whatever follows the colon verbatim, since what follows is the data.
    """
    if detail in CHECK_DETAIL:
        return CHECK_DETAIL[detail]
    prefix, colon, rest = detail.partition(": ")
    if colon and prefix in CHECK_DETAIL:
        return f"{CHECK_DETAIL[prefix]}: {rest}"
    match = _GEN_TIME.match(detail)
    if match:
        stamp, aside = match.group(1), match.group(2)
        # The ISO stamp is kept verbatim, offset and all. This is the technical fold, and it is
        # the one place the exact instant should be readable without a timezone in the way.
        spanish = f"genTime {stamp}"
        if aside:
            spanish += f" ({_GEN_TIME_ASIDE.get(aside, aside)})"
        return spanish
    return detail


def check_label(name: str) -> str:
    """The Spanish gloss for a firmauy check name, or the name itself when there is none."""
    return CHECK_LABEL.get(name, name)


def indication_label(indication: str) -> str:
    """VALID / INDETERMINATE / INVALID in Spanish, or the raw value when it is something else."""
    return INDICATION_LABEL.get(indication, indication or "?")


# --- the timestamp ----------------------------------------------------------

# What a stamp does and does not buy, said once. The same point Ajustes makes beside the TSA
# field, from the other end: there it is a person choosing a provider, here it is a person
# reading a date somebody else's provider put in a file, and the second is where the mistake
# actually costs something.
#
# Ley 18.600 art. 6: "El documento electrónico no hará fe respecto de su fecha, a menos que ésta
# conste a través de un fechado electrónico otorgado por un prestador de servicios de
# certificación acreditado." No provider is named, on purpose: the accredited list belongs to the
# UCE and can grow, and an app that names today's two is wrong the day a third is accredited.
TIMESTAMP_MEANING = (
    "Un sello de tiempo prueba que la firma ya existía en esa fecha. Para que además el documento "
    "haga fe de su fecha, la Ley 18.600 pide un prestador acreditado por la UCE."
)

# Said when the file has no stamp at all. Neutral, because most signed files do not have one and
# not having one is not a defect: it only means the date is not part of what was proved.
NO_TIMESTAMP = "el documento no lleva sello de tiempo"


def timestamp_when(when) -> str:
    """A genTime as a person reads it, in their own clock. Empty when there is no time.

    Shown in local time and labelled as such. RFC 3161 puts the instant in UTC, and rendering
    14:32 to somebody whose clock says 11:32 is a worse failure here than anywhere else in the
    app, because the date *is* the thing this row exists to report. The exact ISO instant,
    offset included, stays one fold below in the technical detail.
    """
    if when is None:
        return ""
    # A naive datetime is read as UTC rather than as local: RFC 3161 genTime is UTC by
    # definition, and astimezone() on a naive value would silently assume the machine's zone.
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return f"{when.astimezone():%d/%m/%Y %H:%M} (hora local)"


def timestamp_value(ts) -> str:
    """What the "Sello de tiempo" row says about ``ts``, a backend.Timestamp or None.

    Reports what is known and stops there. In particular a sound stamp is never called trusted:
    without anchors for the TSA its chain was never evaluated, and the row says who asserted the
    date rather than implying somebody checked.
    """
    if ts is None:
        return NO_TIMESTAMP
    if not ts.sound:
        return check_detail(ts.detail) or "el sello de tiempo está roto"
    when = timestamp_when(ts.gen_time)
    if not when:
        return "tiene sello de tiempo, sin fecha legible"
    if ts.trusted is False:
        return f"{when}, pero la cadena de la TSA no llega a una raíz de confianza"
    if ts.trusted:
        return when
    return f"{when}, según la TSA"


# --- what the screens say when something nobody anticipated goes wrong -------

def unexpected(subject: str = "", *, recorded: bool) -> str:
    """The message for a failure the app has no specific sentence about.

    Never "El detalle quedó en la consola": in the product that is false.
    ``packaging/firmauy-desktop.spec`` sets ``console=False``, which is the whole reason the
    activity record exists: on a packaged build the traceback PySide6 prints has nowhere to go,
    and pointing at the console would point at the one channel the app deliberately removed.

    ``recorded`` is passed in rather than read here, because nothing in this module knows about
    Qt and the record is a Qt path. It is the state of the record right now, not the setting,
    so somebody who already has it on is told where to look instead of being told to switch on
    what is already running.

    ``subject`` is the thing that failed, capitalised and with its article ("La firma"). Empty
    for a screen where the sentence has no room for one.
    """
    opening = f"{subject} falló de una forma inesperada." if subject else \
        "Falló de una forma inesperada."
    if recorded:
        return f"{opening} Quedó anotado en el registro de actividad (Ajustes)."
    return (f"{opening} Si se repite, activá el registro de actividad en Ajustes y volvé a "
            "intentar.")
