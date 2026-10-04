# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the settings store.

The conftest forces the INI backend, which returns every value as a string. That is the
strictest case for the coercers: a boolean comes back as "true", not True, and reading it
straight would make every checkbox permanently on.
"""

from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path

import pytest

from firmauy_desktop import settings
from firmauy_desktop.settings import Settings


def test_defaults_when_nothing_was_ever_saved():
    loaded = settings.load()
    assert loaded == Settings()
    assert loaded.native is True                 # direct PC/SC, the path that needs no middleware
    assert loaded.check_revocation is False      # the network is opt in


def test_every_field_survives_a_round_trip():
    saved = Settings(
        native=False,
        pkcs11_lib="/usr/lib/pkcs11/libgclib.so",
        reader="ACS ACR38U-CCID 00 00",
        tsa_url="https://tsa.example.uy/tsa",
        verify_after_sign=False,
        check_revocation=True,
    )
    settings.save(saved)
    assert settings.load() == saved


# A few fields only accept a fixed set, so "any old string" is not a valid round trip for them.
_ALTERNATIVES = {"appearance": "dark", "stamp_image_mode": "side",
                 "stamp_image_opacity": 0.5, "stamp_corner": "top-right",
                 "stamp_margin": 35}


@pytest.mark.parametrize("field", [f.name for f in fields(Settings())])
def test_each_field_individually(field):
    """One at a time, so a coercer that only works when every flag agrees cannot hide."""
    default = getattr(Settings(), field)
    if isinstance(default, bool):
        other = not default
    else:
        other = _ALTERNATIVES.get(field, "algo distinto")

    settings.save(replace(Settings(), **{field: other}))
    assert getattr(settings.load(), field) == other


def test_a_value_outside_its_domain_falls_back():
    """A hand-edited config file, or one written by an older version that allowed more."""
    settings.save(replace(Settings(), appearance="dark"))
    assert settings.load().appearance == "dark"

    from PySide6.QtCore import QSettings
    QSettings().setValue("appearance", "fosforescente")
    QSettings().sync()

    assert settings.load().appearance == "system"


def test_booleans_come_back_as_booleans_not_strings():
    """The bug this guards: `value("native", True)` is "false" on the INI backend, and "false"
    is truthy, so a user who chose PKCS#11 would keep signing in direct mode."""
    settings.save(replace(Settings(), native=False))
    loaded = settings.load()
    assert loaded.native is False
    assert isinstance(loaded.native, bool)


def test_sign_kwargs_turns_blanks_into_none():
    """firmauy must see None and apply its own defaults, never an empty string."""
    kwargs = settings.sign_kwargs(Settings())
    assert kwargs == {"native": True, "reader": None, "pkcs11_lib": None,
                      "tsa_url": None, "allow_private_network": False, "verify": True,
                      "stamp": _DEFAULT_STAMP}
    # The stamp image is the same rule: "" is the person leaving it empty, and firmauy must see
    # None for that rather than a path of zero characters.
    assert kwargs["stamp"]["image"] is None


def test_sign_kwargs_passes_the_configured_values_through():
    kwargs = settings.sign_kwargs(Settings(
        native=False, reader="ACS", pkcs11_lib="/lib.so", tsa_url="https://t",
        allow_private_network=True, verify_after_sign=False,
    ))
    assert kwargs == {"native": False, "reader": "ACS", "pkcs11_lib": "/lib.so",
                      "tsa_url": "https://t", "allow_private_network": True, "verify": False,
                      "stamp": _DEFAULT_STAMP}


# What firmauy draws when nobody has asked for anything else: the five lines, no image. Spelled
# out rather than computed from Settings() so a default flipping here fails a test instead of
# quietly changing every stamp the app draws.
_DEFAULT_STAMP = {
    # bottom-left with a 20 point margin is the box firmauy has always drawn, so the app's default
    # moves no stamp. That is the assertion, not a restatement of the dataclass.
    "corner": "bottom-left", "margin": 20,
    "image": None, "image_mode": "background", "image_opacity": 0.2,
    "show_title": True, "show_signer": True, "show_document": True,
    "show_date": True, "show_issuer": True,
}


def test_the_stamp_options_carry_every_choice_the_dialog_offers():
    kwargs = settings.sign_kwargs(Settings(
        stamp_image="/logo.png", stamp_image_mode="side", stamp_image_opacity=0.5,
        stamp_document=False, stamp_issuer=False,
    ))
    assert kwargs["stamp"] == {
        "corner": "bottom-left", "margin": 20,
        "image": "/logo.png", "image_mode": "side", "image_opacity": 0.5,
        "show_title": True, "show_signer": True, "show_document": False,
        "show_date": True, "show_issuer": False,
    }


def test_the_other_kwargs_helpers():
    configured = Settings(native=False, reader="ACS", pkcs11_lib="/lib.so",
                          check_revocation=True, allow_private_network=True)
    # tsa_ca is None until the user asks: the anchors exist on the machine either way, and
    # reaching for them unasked would decide who is trusted to say when a document was signed.
    assert settings.verify_kwargs(configured) == {"check_revocation": True, "tsa_ca": None,
                                                  "allow_private_network": True}
    assert settings.doctor_kwargs(configured) == {
        "native": False, "reader": "ACS", "pkcs11_lib": "/lib.so"}
    assert settings.card_kwargs(configured) == {"reader": "ACS"}


def test_nothing_personal_is_storable():
    """A guard on the shape of the store, not on behaviour: SECURITY.md forbids putting the
    cardholder's data or a recent-files list where it outlives an uninstall."""
    names = {f.name for f in fields(Settings())}
    forbidden = {"pin", "recent_files", "last_file", "signer", "id_number", "photo"}
    assert names & forbidden == set()


# --- the anchors a signature timestamp is judged against ----------------------

def test_the_bundled_roots_are_used_when_nobody_named_a_file():
    """A stamp from a public authority needs no setup: its root already ships with the app."""
    where = settings.tsa_anchors(Settings(validate_tsa=True))

    assert where.endswith(".pem")
    assert Path(where).is_file(), "the bundled anchors are not where certifi says they are"


# One root in the public bundle carries a zero serial, which cryptography warns about and will
# one day refuse. It is not ours and not what this test is about.
@pytest.mark.filterwarnings("ignore::cryptography.utils.CryptographyDeprecationWarning")
def test_the_bundled_roots_can_actually_judge_a_public_authority():
    """The bundle is not just present, it contains what it needs to.

    Named here rather than in the app, and only in a test: a fixture may name a real authority to
    prove the bundle is the right one, where the UI naming a provider would read as a
    recommendation and would be wrong the day the accredited list changes.
    """
    from cryptography import x509

    pem = Path(settings.tsa_anchors(Settings(validate_tsa=True))).read_bytes()
    names = set()
    for block in pem.split(b"-----BEGIN CERTIFICATE-----")[1:]:
        cert = x509.load_pem_x509_certificate(b"-----BEGIN CERTIFICATE-----" + block)
        names.update(a.value for a in cert.subject if a.oid._name == "commonName")

    assert "DigiCert Trusted Root G4" in names


def test_a_named_file_wins_over_the_bundled_roots():
    """The case the bundle cannot cover: an accredited Uruguayan provider, whose certificate is
    in no public bundle and arrives with the subscription."""
    assert settings.tsa_anchors(Settings(validate_tsa=True, tsa_ca="/mi/tsa.pem")) == "/mi/tsa.pem"


def test_the_anchors_only_travel_when_the_box_is_ticked():
    assert settings.verify_kwargs(Settings(tsa_ca="/mi/tsa.pem"))["tsa_ca"] is None
    assert settings.verify_kwargs(Settings(validate_tsa=True, tsa_ca="/mi/tsa.pem"))["tsa_ca"] \
        == "/mi/tsa.pem"


def test_the_corner_and_margin_reach_the_stamp_options():
    """The point of the 1.17.0 floor. A corner chosen in Ajustes has to arrive as firmauy's, or
    the stamp keeps landing in the one place it always did."""
    kwargs = settings.sign_kwargs(Settings(stamp_corner="top-right", stamp_margin=45))
    assert kwargs["stamp"]["corner"] == "top-right"
    assert kwargs["stamp"]["margin"] == 45


def test_a_stored_corner_or_margin_outside_its_domain_falls_back():
    """A hand-edited store must not reach firmauy, which refuses both and would raise at signing
    time, on a screen the person cannot do anything about."""
    settings.save(Settings())
    from PySide6.QtCore import QSettings

    store = QSettings()
    store.setValue("stamp_corner", "middle")
    store.setValue("stamp_margin", -5)
    store.sync()

    loaded = settings.load()
    assert loaded.stamp_corner == "bottom-left"
    assert loaded.stamp_margin == 20


def _store_raw(key: str, value: str) -> None:
    """What a hand edit leaves: a string, which is how the INI backend hands every value back."""
    from PySide6.QtCore import QSettings

    store = QSettings()
    store.setValue(key, value)
    store.sync()


@pytest.mark.parametrize("raw", ["inf", "-inf", "1e400", "nan", "1e300", "3000000000", "201",
                                 "-5", "veinte", ""])
def test_a_margin_ajustes_cannot_show_falls_back(raw):
    """"inf" made int() raise OverflowError inside load(), so the app did not start. Past a C int
    the spin box raised it instead and Ajustes did not open. And anything above what the spin
    box offers would be clamped there and saved back as a margin nobody chose."""
    settings.save(Settings())
    _store_raw("stamp_margin", raw)

    assert settings.load().stamp_margin == 20


@pytest.mark.parametrize("raw, expected", [("0", 0), ("45", 45),
                                           (str(settings.STAMP_MARGIN_MAX),
                                            settings.STAMP_MARGIN_MAX)])
def test_a_margin_ajustes_can_show_is_kept(raw, expected):
    settings.save(Settings())
    _store_raw("stamp_margin", raw)

    assert settings.load().stamp_margin == expected


def test_a_geometry_that_is_not_ascii_is_not_handed_to_the_window():
    """The app writes it as base64. The window encodes it as ASCII to decode it, which raised on
    anything else and stopped the window from opening."""
    settings.save(Settings())
    _store_raw("window_geometry", "ñ")

    assert settings.load().window_geometry == ""
