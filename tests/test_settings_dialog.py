# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the Ajustes dialog. Built headless, never exec()'d."""

from __future__ import annotations

from firmauy_desktop import settings
from firmauy_desktop.settings import Settings
from firmauy_desktop.views.settings_dialog import SettingsDialog


def test_the_dialog_shows_what_is_stored(qtbot):
    current = Settings(native=False, pkcs11_lib="/lib.so", reader="ACS",
                       tsa_url="https://t", verify_after_sign=False, check_revocation=True)
    dialog = SettingsDialog(current)
    qtbot.addWidget(dialog)

    assert dialog._pkcs11.isChecked() is True
    assert dialog._lib.text() == "/lib.so"
    assert dialog._reader.text() == "ACS"
    assert dialog._tsa.text() == "https://t"
    assert dialog._verify_after.isChecked() is False
    assert dialog._revocation.isChecked() is True


def test_accepting_collects_the_edits(qtbot):
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    dialog._pkcs11.setChecked(True)
    dialog._lib.setText("  /usr/lib/pkcs11/libgclib.so  ")   # trimmed on the way out
    dialog._reader.setText("ACS ACR38U")
    dialog._revocation.setChecked(True)
    dialog._on_accept()

    assert dialog.result_settings == Settings(
        native=False,
        pkcs11_lib="/usr/lib/pkcs11/libgclib.so",
        reader="ACS ACR38U",
        tsa_url="",
        verify_after_sign=True,
        check_revocation=True,
    )


def test_the_module_path_only_applies_on_the_pkcs11_path(qtbot):
    """A module path is meaningless in direct mode, so it must not look editable there."""
    dialog = SettingsDialog(Settings(native=True))
    qtbot.addWidget(dialog)
    assert dialog._lib_row.isEnabled() is False

    dialog._pkcs11.setChecked(True)
    assert dialog._lib_row.isEnabled() is True


def test_cancelling_changes_nothing_on_disk(qtbot):
    settings.save(Settings(native=True, reader="original"))

    dialog = SettingsDialog(settings.load())
    qtbot.addWidget(dialog)
    dialog._reader.setText("editado")
    dialog.reject()                                          # no _on_accept, so no save

    assert settings.load().reader == "original"


def test_the_timestamp_field_says_what_a_stamp_buys(qtbot):
    """The field takes any RFC 3161 URL and said nothing about what one gets from it, which is
    not the same for every provider.

    Ley 18.600 art. 6: a document does not make faith as to its date unless the timestamp comes
    from an accredited provider. A stamp from anybody else is real cryptographic evidence of when
    the signature existed, and is not that. An app careful enough to say "Revocación no
    consultada" should not leave this one implied.
    """
    from conftest import widget_text

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    text = widget_text(dialog)

    assert "18.600" in text
    assert "UCE" in text
    assert "haga fe de su fecha" in text


def test_the_timestamp_note_names_no_provider(qtbot):
    """The accredited list belongs to the UCE and can grow. An app that names two providers today
    is an app that is wrong the day a third is accredited."""
    from conftest import widget_text

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    text = widget_text(dialog).lower()

    for provider in ("abitab", "antel", "digicert"):
        assert provider not in text


def test_the_local_network_stays_closed_until_asked_and_says_what_opening_it_costs(qtbot):
    """firmauy reaches only public addresses unless asked, so a URL cannot carry a request into
    the network the computer sits on. The box is the asking. Its note has to say the half nobody
    would guess: with it on, verifying with revocation follows addresses out of certificates in
    files other people sent."""
    from conftest import widget_text

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    assert dialog._private_network.isChecked() is False
    assert "certificado de un archivo ajeno" in widget_text(dialog)

    dialog._private_network.setChecked(True)
    dialog._on_accept()
    assert dialog.result_settings.allow_private_network is True


def test_the_margin_box_offers_exactly_what_the_store_keeps(qtbot):
    """load() refuses a margin the spin box cannot show, so the two agree on one range or a
    margin chosen here comes back as the default."""
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    assert (dialog._stamp_margin.minimum(), dialog._stamp_margin.maximum()) == (
        0, settings.STAMP_MARGIN_MAX)


def test_the_stamp_choices_survive_a_round_trip(qtbot):
    """Every one of them ends up in a PdfAppearance, so a choice lost here is a stamp that
    silently keeps printing what the person turned off."""
    current = Settings(stamp_image="/logo.png", stamp_image_mode="side",
                       stamp_image_opacity=0.35, stamp_document=False, stamp_issuer=False,
                       stamp_corner="top-right", stamp_margin=45)
    dialog = SettingsDialog(current)
    qtbot.addWidget(dialog)

    assert dialog._stamp_corner.currentData() == "top-right"
    assert dialog._stamp_margin.value() == 45
    assert dialog._stamp_image.text() == "/logo.png"
    assert dialog._stamp_mode.currentData() == "side"
    assert dialog._stamp_opacity.value() == 35          # stored 0..1, shown as a percentage
    assert dialog._stamp_document.isChecked() is False
    assert dialog._stamp_issuer.isChecked() is False
    assert dialog._stamp_title.isChecked() is True

    dialog._on_accept()
    saved = dialog.result_settings
    assert saved.stamp_corner == "top-right"
    assert saved.stamp_margin == 45
    assert saved.stamp_image == "/logo.png"
    assert saved.stamp_image_mode == "side"
    assert saved.stamp_image_opacity == 0.35
    assert (saved.stamp_document, saved.stamp_issuer, saved.stamp_title) == (False, False, True)


def test_the_stamp_controls_that_cannot_do_anything_are_disabled(qtbot, tmp_path):
    """A control on screen that has no effect is a worse answer than a greyed out one.

    Three rules, and the first is the one this dialog got wrong for a while: with no image there
    is no layout to choose and nothing to fade, and those two rows sat there live and inert.
    """
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"not really a png, and never opened here")

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    lines = [getattr(dialog, attr) for attr, _, _ in dialog._STAMP_LINES]

    # No image at all: nothing about an image can be chosen, and every line is still available.
    assert dialog._stamp_mode.isEnabled() is False
    assert dialog._stamp_opacity.isEnabled() is False
    assert all(check.isEnabled() for check in lines)

    dialog._stamp_image.setText(str(logo))
    assert dialog._stamp_mode.isEnabled() is True
    assert dialog._stamp_opacity.isEnabled() is True       # background is the default mode

    dialog._stamp_mode.setCurrentIndex(dialog._stamp_mode.findData("side"))
    assert dialog._stamp_opacity.isEnabled() is False      # nothing to fade beside the text
    assert all(check.isEnabled() for check in lines)

    dialog._stamp_mode.setCurrentIndex(dialog._stamp_mode.findData("only"))
    assert dialog._stamp_opacity.isEnabled() is False
    assert not any(check.isEnabled() for check in lines)   # no text is drawn to pick from

    # And taking the image away puts it all back the way it started.
    dialog._stamp_image.clear()
    assert dialog._stamp_mode.isEnabled() is False
    assert all(check.isEnabled() for check in lines)


def test_the_stamp_tab_groups_its_rows_under_headings(qtbot):
    """Flat, the five rows read as one list: "Separación" says nothing without the corner above
    it, and "Cómo se usa" and "Opacidad" belong to the image and to nothing else."""
    from PySide6.QtWidgets import QLabel

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    page = dialog._tabs.widget(2)
    headings = [lbl.text() for lbl in page.findChildren(QLabel)
                if lbl.property("role") == "subtitle"]

    assert headings == ["Dónde va en la página", "Imagen", "Qué muestra la estampa"]


def test_a_stamp_image_that_is_not_there_is_refused_before_the_card(qtbot, tmp_path):
    """PdfAppearance validates when it is built, and backend builds it before touching the card.
    The person gets a sentence about Ajustes instead of a spent PIN try."""
    from firmauy_desktop import backend

    result = backend.sign_file(str(tmp_path / "d.pdf"), "1234",
                               **settings.sign_kwargs(Settings(stamp_image="/nowhere/logo.png")))

    assert result.ok is False
    assert result.error_kind == "stamp"
    assert "imagen de la estampa" in result.detail
    assert "Ajustes" in result.detail


def test_the_default_corner_is_the_one_the_stamp_has_always_used(qtbot):
    """A fresh install must not move anybody's stamp. bottom-left at 20 points is the box firmauy
    draws with no appearance at all, and the dialog opening on anything else would silently
    relocate every signature made after an update."""
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    assert dialog._stamp_corner.currentData() == "bottom-left"
    assert dialog._stamp_margin.value() == 20

    dialog._on_accept()
    stamp = settings.sign_kwargs(dialog.result_settings)["stamp"]
    assert (stamp["corner"], stamp["margin"]) == ("bottom-left", 20)


def test_every_corner_the_combo_offers_is_one_firmauy_accepts(qtbot):
    """The combo is the only source of this value, so a label paired with a typo would only show
    up as a failure after the PIN. PdfAppearance is the authority on the four names."""
    from firmauy.api import PdfAppearance

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    offered = [dialog._stamp_corner.itemData(i) for i in range(dialog._stamp_corner.count())]
    assert len(offered) == 4
    for corner in offered:
        PdfAppearance(corner=corner)                # raises ValueError on an unknown name


def test_the_dialog_fits_on_the_screen_it_is_shown_on(qtbot):
    """Measured before the tabs existed: the four groups stacked wanted 1093 points, which does
    not fit on a 1920x1080 desktop once the title bar and the task bar are gone. What falls off
    the bottom of a dialog is its buttons, so Guardar and Cancelar were the unreachable part, and
    only on somebody else's machine. Tabs make it as tall as one page instead of all four.
    """
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QDialogButtonBox

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    screen = QGuiApplication.primaryScreen()
    assert screen is not None, "no screen to measure against, so this proves nothing"

    assert dialog.sizeHint().height() <= screen.availableGeometry().height()
    # 668 is what a 1366x768 laptop leaves. Asserted as a number so growth that would push the
    # dialog off the smallest common screen fails here rather than in somebody's screenshot.
    assert dialog.sizeHint().height() <= 668

    buttons = dialog.findChild(QDialogButtonBox)
    assert buttons.parent() is dialog, "the buttons must not live inside a tab"


def test_every_group_is_a_tab_and_none_was_dropped(qtbot):
    from PySide6.QtWidgets import QTabWidget

    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    tabs = dialog.findChild(QTabWidget)

    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Apariencia", "Firma", "Estampa", "Verificación", "Diagnóstico"]


def test_a_tab_nobody_opened_still_saves_its_settings(qtbot):
    """The classic way tabs lose data. Every page is built up front and Guardar reads all of
    them, so a setting stored on a tab the person never clicked has to survive anyway.
    """
    dialog = SettingsDialog(Settings(stamp_corner="top-right", check_revocation=True))
    qtbot.addWidget(dialog)

    from PySide6.QtWidgets import QTabWidget
    assert dialog.findChild(QTabWidget).currentIndex() == 0    # only Apariencia was ever shown

    dialog._on_accept()
    assert dialog.result_settings.stamp_corner == "top-right"
    assert dialog.result_settings.check_revocation is True


def test_accepting_the_dialog_keeps_every_setting_it_does_not_show(qtbot):
    """_on_accept builds a Settings field by field, so a field added anywhere else is dropped in
    silence: the dialog rebuilds the object without it and Guardar writes the default over what
    was there. window_geometry_min was added and lost exactly this way, which would have made the
    window forget its size on the first visit to Ajustes.

    The input is derived from the dataclass rather than written out by hand, because a hand-built
    one silently defaults any field it does not know about and then agrees with the dialog about
    it. That is a test passing by not looking, and it is exactly how this test first failed to
    cover activity_log.
    """
    from dataclasses import fields, replace

    # The few fields that only accept a fixed set or a range. Everything else is flipped
    # generically, so a field added later is covered the day it is added.
    NAMED = {"appearance": "dark", "stamp_image_mode": "side", "stamp_corner": "top-right",
             "stamp_image_opacity": 0.35, "stamp_margin": 45,
             "window_geometry": "Z2VvbWV0cnk=", "window_geometry_min": "720x560"}

    def other(field):
        if field.name in NAMED:
            return NAMED[field.name]
        default = getattr(Settings(), field.name)
        return (not default) if isinstance(default, bool) else "algo distinto"

    stored = replace(Settings(), **{f.name: other(f) for f in fields(Settings)})
    # The guard that makes the rest mean anything: every field really did move off its default.
    assert all(getattr(stored, f.name) != getattr(Settings(), f.name) for f in fields(Settings))

    dialog = SettingsDialog(stored)
    qtbot.addWidget(dialog)
    dialog._on_accept()

    lost = [f.name for f in fields(Settings)
            if getattr(dialog.result_settings, f.name) != getattr(stored, f.name)]
    assert lost == [], f"the dialog dropped {lost}"
