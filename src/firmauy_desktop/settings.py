# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""What the app remembers between runs, and how it becomes backend arguments.

Backed by QSettings, which derives its location from the application's name rather than from
``__file__`` or ``sys.executable``. That matters for a frozen build: a JSON file beside the
module would land inside PyInstaller's temporary extraction directory (wiped every run) or
inside the application directory, which may be read only and, on macOS, cannot be written to
without breaking the bundle's signature.

Nothing outside this module touches QSettings. The INI backend hands every value back as a
string, so ``value("native", True)`` comes back as ``"true"``, and letting that loose in the
views is the classic way this goes wrong. The dataclass is the only type the rest of the app
sees.

**What is never stored:** the PIN, anything read off the cédula (name, number, photo,
certificate serial), and any list of recent files. A recent-files list would put the names of
the cardholder's documents into a plist or the registry, where they outlive the uninstall. That
is squarely SECURITY.md's "leaking the cardholder's data", so it is a deliberate non-feature,
written down because it is the first thing anyone will ask for.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Optional

from PySide6.QtCore import QSettings

ORG = "firmauy"
APP = "FirmaUY Desktop"

# The one name the desktop knows this application by, on every platform: the base name of its
# desktop entry on Linux, its bundle identifier on macOS, and what a compositor matches a window
# against. Reverse DNS under a domain that is actually registered, which is what makes the form
# mean anything, and permanent: changing it after a release orphans the installed entry, the icon
# and whatever a catalogue recorded, and leaves a second application sitting beside the first.
#
# The files named after it live in packaging/linux/, and a test holds them and the macOS bundle
# identifier to this string, because three copies of a name is how two of them go stale.
APP_ID = "com.firmauy.firmauydesktop"

# The widest gap Ajustes offers between the stamp and its corner's two edges, in points. firmauy
# takes any distance that is not negative, so this is the app's own limit, and it lives here so
# the spin box and load() share one number: a stored value the spin box cannot show never gets
# to it.
STAMP_MARGIN_MAX = 200


@dataclass
class Settings:
    """Every field here has a live consumer. Add one when its consumer lands, not before."""

    native: bool = True                 # PC/SC direct, the path that needs no middleware
    pkcs11_lib: str = ""                # "" means firmauy's own DEFAULT_PKCS11_LIB
    reader: str = ""                    # "" means autodetect
    tsa_url: str = ""                   # "" means no timestamp. Uses the network when set
    # Whether the TSA and the revocation lookups may reach a loopback or private address. firmauy
    # refuses those unless asked, so a URL cannot send a request into somebody's own network, and
    # an internal TSA or CRL/OCSP mirror is the reason to ask. Off by default for the same reason,
    # and a link-local address stays refused either way.
    allow_private_network: bool = False
    verify_after_sign: bool = True      # re-check the fresh signature, local and cheap
    check_revocation: bool = False      # the only network I/O in verification, so opt in
    # Whether to judge who issued a signature timestamp. Off by default and not because it is
    # expensive (it is offline and instant), but because it is a trust decision: nobody has said
    # they accept the bundled public roots as timestamping authorities, and an app that assumes
    # that on their behalf has decided something for them without asking.
    validate_tsa: bool = False
    tsa_ca: str = ""                    # "" means the bundled public roots; a PEM path overrides
    # The visible stamp drawn on a signed PDF. It is ink on a page and not the signature: with
    # every line off the file still verifies exactly the same, because the signer, the issuer and
    # the time live inside the signature where the cryptography covers them. Persisted rather than
    # asked per document, since a logo is something you choose once.
    # Which corner of the page carries it, resolved by firmauy against that page's real size.
    # "bottom-left" with a 20 point margin is the box firmauy has always drawn, so the default
    # changes nothing. The default box reaches 90 points up the page, which is above a typical
    # bottom margin, so on a document with text to the foot it lands on the words. This is the
    # way out of that, and it needs the page size, which is why it took a core release.
    stamp_corner: str = "bottom-left"   # bottom-left | bottom-right | top-left | top-right
    stamp_margin: int = 20              # points from the two page edges of that corner
    stamp_image: str = ""               # "" means the text block alone
    stamp_image_mode: str = "background"    # background | side | only
    stamp_image_opacity: float = 0.2    # how faded, in background mode
    stamp_title: bool = True            # "Firma electrónica avanzada, UY"
    stamp_signer: bool = True           # "Firmado por: ..."
    stamp_document: bool = True         # "Documento: ..." (the certificate serial, not the cédula)
    stamp_date: bool = True             # "Fecha: ..."
    stamp_issuer: bool = True           # the issuing authority
    advanced_mode: bool = False         # shows the PKCS#11 introspection screen
    # An opt-in record of what the app did, for reporting a problem. Off by default and named
    # here rather than in activity.py because this dataclass is the disk contract: everything the
    # app persists is a field of it, so a reader can see in one place that the record is a choice
    # and not something that happens to somebody.
    activity_log: bool = False
    appearance: str = "system"          # system | light | dark
    # QWidget.saveGeometry() as base64. A string rather than the QByteArray Qt hands over,
    # because the INI and registry backends round-trip that type differently.
    window_geometry: str = ""
    # The minimum size in force when that geometry was saved, as "WxH". A geometry saved under a
    # smaller minimum comes back clamped: a size nobody chose, at a position from another layout.
    # Storing what it was measured against is what lets the restore tell stale from deliberate.
    window_geometry_min: str = ""


def apply_identity(app) -> None:
    """Name the application so QSettings knows where to write.

    Must run before anything constructs a QSettings, or Linux silently writes to
    ``~/.config/Unknown Organization/``.
    """
    app.setOrganizationName(ORG)
    app.setApplicationName(APP)
    # Which desktop entry is this window. Qt's own words: it is needed by the windowing system to
    # retrieve that "without resorting to imprecise heuristics", and the heuristics are what put a
    # generic icon in the task switcher and split one application into two entries under Wayland.
    # The base name, with no path and no ".desktop" on the end.
    app.setDesktopFileName(APP_ID)


def load() -> Settings:
    store = QSettings()
    return Settings(
        native=_get_bool(store, "native", True),
        pkcs11_lib=_get_str(store, "pkcs11_lib"),
        reader=_get_str(store, "reader"),
        tsa_url=_get_str(store, "tsa_url"),
        allow_private_network=_get_bool(store, "allow_private_network", False),
        verify_after_sign=_get_bool(store, "verify_after_sign", True),
        check_revocation=_get_bool(store, "check_revocation", False),
        validate_tsa=_get_bool(store, "validate_tsa", False),
        tsa_ca=_get_str(store, "tsa_ca"),
        stamp_corner=_one_of(_get_str(store, "stamp_corner", "bottom-left"),
                             ("bottom-left", "bottom-right", "top-left", "top-right"),
                             "bottom-left"),
        stamp_margin=_get_int(store, "stamp_margin", 20, STAMP_MARGIN_MAX),
        stamp_image=_get_str(store, "stamp_image"),
        stamp_image_mode=_one_of(_get_str(store, "stamp_image_mode", "background"),
                                 ("background", "side", "only"), "background"),
        stamp_image_opacity=_get_float(store, "stamp_image_opacity", 0.2),
        stamp_title=_get_bool(store, "stamp_title", True),
        stamp_signer=_get_bool(store, "stamp_signer", True),
        stamp_document=_get_bool(store, "stamp_document", True),
        stamp_date=_get_bool(store, "stamp_date", True),
        stamp_issuer=_get_bool(store, "stamp_issuer", True),
        advanced_mode=_get_bool(store, "advanced_mode", False),
        activity_log=_get_bool(store, "activity_log", False),
        appearance=_one_of(_get_str(store, "appearance", "system"),
                           ("system", "light", "dark"), "system"),
        window_geometry=_get_ascii(store, "window_geometry"),
        window_geometry_min=_get_str(store, "window_geometry_min"),
    )


def save(settings: Settings) -> None:
    store = QSettings()
    for field in fields(settings):
        store.setValue(field.name, getattr(settings, field.name))
    store.sync()        # macOS caches through cfprefsd, so do not wait for the destructor


def sign_kwargs(settings: Settings) -> dict:
    """The signing arguments the settings decide.

    One function rather than six loose keyword arguments at every call site. Empty strings become
    None so firmauy applies its own defaults instead of receiving "".
    """
    return {
        "native": settings.native,
        "reader": _or_none(settings.reader),
        "pkcs11_lib": _or_none(settings.pkcs11_lib),
        "tsa_url": _or_none(settings.tsa_url),
        "allow_private_network": settings.allow_private_network,
        "verify": settings.verify_after_sign,
        "stamp": stamp_options(settings),
    }


def stamp_options(settings: Settings) -> dict:
    """The visible stamp, as the keyword arguments firmauy's PdfAppearance takes.

    Plain values rather than the object itself, so this module stays free of firmauy: backend.py
    is where the two vocabularies meet, and it is also where a bad image path has to become a
    Spanish sentence instead of an exception.
    """
    return {
        "corner": settings.stamp_corner,
        "margin": settings.stamp_margin,
        "image": _or_none(settings.stamp_image),
        "image_mode": settings.stamp_image_mode,
        "image_opacity": settings.stamp_image_opacity,
        "show_title": settings.stamp_title,
        "show_signer": settings.stamp_signer,
        "show_document": settings.stamp_document,
        "show_date": settings.stamp_date,
        "show_issuer": settings.stamp_issuer,
    }


def verify_kwargs(settings: Settings) -> dict:
    return {
        "check_revocation": settings.check_revocation,
        "tsa_ca": tsa_anchors(settings) if settings.validate_tsa else None,
        "allow_private_network": settings.allow_private_network,
    }


def tsa_anchors(settings: Settings) -> str:
    """The PEM bundle a signature timestamp's own chain is judged against.

    The user's file when they named one, and the public roots the app ships otherwise. Those two
    cover the two situations that actually happen: a stamp from a public authority, whose root
    every machine already has, and a stamp from an accredited Uruguayan provider, whose
    certificate is not in any public bundle and arrives with the subscription.

    Deliberately not the operating system's own store. It is the same set on most machines, but
    reaching for it silently would mean the app decided that whatever the OS trusts for the web
    is also trusted to say when a document was signed, which is not a decision it was given.
    Shipping the list makes it inspectable and the same on every platform.
    """
    if settings.tsa_ca:
        return settings.tsa_ca
    import certifi

    return certifi.where()


def doctor_kwargs(settings: Settings) -> dict:
    return {
        "native": settings.native,
        "reader": _or_none(settings.reader),
        "pkcs11_lib": _or_none(settings.pkcs11_lib),
    }


def card_kwargs(settings: Settings) -> dict:
    """Reading the cédula goes over PC/SC, so only the reader applies."""
    return {"reader": _or_none(settings.reader)}


def _or_none(value: str) -> Optional[str]:
    return value or None


def _get_bool(store: QSettings, key: str, default: bool) -> bool:
    """The INI backend returns "true"/"false" and the Windows registry returns real booleans."""
    value = store.value(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _one_of(value: str, allowed: tuple[str, ...], fallback: str) -> str:
    """A stored value outside the set means a hand-edited file or an older version."""
    return value if value in allowed else fallback


def _get_int(store: QSettings, key: str, default: int, maximum: int) -> int:
    """Like _get_float, for a value in points, and held to what Ajustes can show.

    Negative is refused because firmauy refuses it, and a stored one would otherwise only surface
    as a failure at signing time. Above ``maximum`` is refused because the spin box showing it
    cannot: past what a C int holds it raised OverflowError and Ajustes never opened. And float()
    turns a hand-edited "inf" into infinity, whose int() raised OverflowError right here, before
    the window existed.
    """
    try:
        value = int(float(store.value(key, default)))
    except (TypeError, ValueError, OverflowError):
        return default
    return value if 0 <= value <= maximum else default


def _get_float(store: QSettings, key: str, default: float) -> float:
    """The INI backend hands back the string it wrote. A value that is not a number, or is outside
    the range firmauy accepts, comes from a hand-edited file and falls back rather than raising on
    a screen the person cannot see."""
    try:
        value = float(store.value(key, default))
    except (TypeError, ValueError):
        return default
    return value if 0.0 <= value <= 1.0 else default


def _get_str(store: QSettings, key: str, default: str = "") -> str:
    value = store.value(key, default)
    return "" if value is None else str(value)


def _get_ascii(store: QSettings, key: str) -> str:
    """A value the app only ever writes as ASCII, the base64 of a geometry. Anything else was
    edited by hand, and the window's encode("ascii") on it raised before the window opened."""
    value = _get_str(store, key)
    return value if value.isascii() else ""
