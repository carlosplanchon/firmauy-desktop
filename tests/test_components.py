# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the widget library the screens are about to be rebuilt from.

Two themes run through these. Hostile text must arrive **intact**, which is a stronger claim than
the old "escaped but mangled": a PlainText label cannot be talked into rendering markup at all.
And a container that rebuilds itself must not leave its old children behind, which is the quiet
failure this kind of conversion invites.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from conftest import widget_text
from firmauy_desktop.ui import components as c
from firmauy_desktop.ui.theming import theme

# What an attacker puts in a certificate's common name. The img tag used to make QTextDocument
# resolve a local resource, and the bare < swallowed the rest of the line.
_HOSTILE = '<img src="file:///etc/passwd">JUAN <PEREZ & CIA'
_SHA256 = "96ccc62287f54cfa28c8ec24c6f960b7da403a0c4100c3d32c50e37fa7a73764"


# --- the label ---------------------------------------------------------------

def test_a_label_is_always_plain_text(qapp):
    """The whole reason this conversion deletes a bug class rather than porting it."""
    made = c.label(_HOSTILE)
    assert made.textFormat() == Qt.TextFormat.PlainText
    assert made.text() == _HOSTILE          # intact, not escaped into something else


def test_a_value_can_be_selected(qapp):
    """People copy certificate serials and digests out of these screens."""
    plain = c.label("x")
    picked = c.label("x", selectable=True)
    # A QLabel starts at LinksAccessibleByMouse, not at nothing, so the claim is about the one
    # flag that matters rather than about the whole set.
    assert not (plain.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse)
    assert picked.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


# --- the tooltip -------------------------------------------------------------

def _shown_by_a_tooltip(tooltip: str) -> str:
    """What a tooltip puts on screen. Qt draws it on AutoText: markup if it looks like markup."""
    from PySide6.QtGui import QTextDocument
    from PySide6.QtGui import Qt as GuiQt

    document = QTextDocument()
    if GuiQt.mightBeRichText(tooltip):
        document.setHtml(tooltip)
    else:
        document.setPlainText(tooltip)
    return document.toPlainText()


def test_without_help_a_tooltip_reads_a_file_name_as_markup(qapp):
    """The premise, held here so that a Qt which stopped guessing would show up as a failure."""
    name = "/home/ana/<b>FACTURA</b> PAGADA.pdf\nya estaba firmado"
    assert _shown_by_a_tooltip(name) == "/home/ana/FACTURA PAGADA.pdf ya estaba firmado"


@pytest.mark.parametrize("text", [
    _HOSTILE,
    "/home/ana/<b>FACTURA</b>  PAGADA.pdf\nya estaba firmado",
    "contrato & anexo.pdf",
    "acta.pdf",
])
def test_a_tooltip_shows_hostile_text_intact(qapp, text):
    """Intact, like a label: tags, ampersands, a double space and the line break included."""
    assert _shown_by_a_tooltip(c.plain_tooltip(text)) == text


def test_a_file_row_tooltip_shows_the_name_as_written(qtbot):
    """The row's tooltip carries the whole path and what happened to the file, and both can come
    from whoever named the file. A name with a tag in it came out in bold, with the detail
    pulled up onto the same line."""
    from firmauy_desktop.widgets import FileListWidget

    files = FileListWidget()
    qtbot.addWidget(files)
    path = "/tmp/<b>FACTURA</b>  PAGADA.pdf"
    files.set_paths([path])
    assert _shown_by_a_tooltip(files.item(0).toolTip()) == path

    files.set_status(path, "failed", "chocaría con <i>copia</i>.pdf")
    assert _shown_by_a_tooltip(files.item(0).toolTip()) == f"{path}\nchocaría con <i>copia</i>.pdf"


def test_role_and_tone_are_properties_the_stylesheet_reads(qapp):
    made = c.label("x", role="title", tone="ok")
    assert made.property("role") == "title"
    assert made.property("tone") == "ok"


def test_setting_a_tone_afterwards_restyles(qapp):
    """Qt resolves a stylesheet once, at polish time, and a later property change does nothing
    on its own. set_tone exists so nobody has to remember that."""
    made = c.label("x")
    assert made.property("tone") is None
    c.set_tone(made, "bad")
    assert made.property("tone") == "bad"
    c.set_tone(made, "")
    assert made.property("tone") is None


def test_a_note_is_muted_without_being_disabled(qapp):
    """Three labels used to be setEnabled(False) purely to render grey, which a screen reader
    announces as unavailable."""
    note = c.Note("Usa internet y puede demorar.")
    assert note.isEnabled() is True
    assert note.property("tone") == "muted"


# --- the marks ---------------------------------------------------------------

def test_a_mark_shows_nothing_when_the_answer_is_unknown(qapp):
    """None is not a third state to draw, it is the absence of a claim."""
    assert c.Mark(None).state() is None
    assert c.Mark(None).isHidden() is True
    assert c.Mark(True).isHidden() is False


def test_a_mark_changes_with_its_state(qapp):
    mark = c.Mark(True)
    yes = mark.pixmap().toImage()
    mark.set_state(False)
    assert mark.pixmap().toImage() != yes
    mark.set_state(None)
    assert mark.isHidden() is True


def test_a_status_icon_reports_what_it_shows(qapp):
    icon = c.StatusIcon("PASS")
    assert icon.status() == "PASS"
    assert not icon.pixmap().isNull()
    icon.set_status("FAIL")
    assert icon.status() == "FAIL"


def test_an_unknown_status_still_draws_something(qapp):
    """firmauy is free to add a status, and a blank cell reads as a missing row."""
    assert not c.StatusIcon("ALGO_NUEVO").pixmap().isNull()


# --- the key/value list ------------------------------------------------------

def test_a_key_value_list_shows_its_rows(qapp):
    kv = c.KeyValueList()
    kv.set_rows([c.Row("Nombre", "PEREZ PEREZ JUAN"), c.Row("Cédula", "DNI12345672")])

    text = widget_text(kv)
    assert "Nombre:" in text
    assert "PEREZ PEREZ JUAN" in text
    assert "DNI12345672" in text


def test_a_hostile_value_arrives_intact(qapp):
    kv = c.KeyValueList()
    kv.set_rows([c.Row("Nombre", _HOSTILE)])
    assert _HOSTILE in widget_text(kv)      # not mangled, and not rendered either


def test_a_row_can_carry_a_mark(qapp):
    kv = c.KeyValueList()
    kv.set_rows([c.Row("Cadena", "llega a la raíz", mark=True),
                 c.Row("Otra", "no llega", mark=False),
                 c.Row("Tercera", "sin opinión")])
    marks = kv.findChildren(c.Mark)
    assert [m.state() for m in marks] == [True, False]   # the third row has no mark at all


def test_setting_rows_twice_leaves_no_orphans(qapp):
    """The quiet failure: the old children stay alive, stacked and invisible, and the label count
    climbs on every update."""
    kv = c.KeyValueList()
    kv.set_rows([c.Row("a", "1"), c.Row("b", "2")])
    first = len(kv.findChildren(QLabel))

    for _ in range(5):
        kv.set_rows([c.Row("a", "1"), c.Row("b", "2")])

    assert len(kv.findChildren(QLabel)) == first


def test_a_long_name_wraps_instead_of_widening_the_screen(qapp):
    """The named risk of this whole conversion: a grid cell does not wrap by itself, so a
    sixty-character common name would push a horizontal scrollbar onto the screen."""
    kv = c.KeyValueList()
    kv.set_rows([c.Row("Nombre", "MARÍA DE LOS ÁNGELES RODRÍGUEZ FERNÁNDEZ DE LA CUESTA")])
    value = [lbl for lbl in kv.findChildren(QLabel) if "ÁNGELES" in lbl.text()][0]

    assert value.wordWrap() is True
    assert value.minimumWidth() <= 1         # so the grid is allowed to shrink it
    assert kv._grid.columnStretch(1) > 0
    assert kv.minimumSizeHint().width() < 200


def test_a_digest_is_never_shown_half(qapp):
    """The other half of that risk, and the one that bites harder.

    Measured: word wrap only breaks at spaces, so a sha256 stays on one line at every width and
    gets clipped. A clipped digest looks exactly like a complete one, which is the wrong way for
    this to fail. It gets the full width of its own line and a minimum that fits all of it.
    """
    kv = c.KeyValueList()
    kv.set_rows([c.Row("Huella", _SHA256, role="mono")])
    value = [lbl for lbl in kv.findChildren(QLabel) if _SHA256 in lbl.text()][0]

    assert value.minimumWidth() >= value.fontMetrics().horizontalAdvance(_SHA256)
    assert kv._grid.getItemPosition(kv._grid.indexOf(value))[3] == 3   # spans every column
    # Small enough that the window minimum covers it, so the guarantee costs no scrollbar.
    assert kv.minimumSizeHint().width() < 480


def test_a_short_serial_stays_beside_its_label(qapp):
    """Only what cannot fit escapes to its own line. A sixteen-character card serial down there
    reads as a layout mistake rather than as a decision."""
    kv = c.KeyValueList()
    kv.set_rows([c.Row("Serie", "66000034D0201077", role="mono")])
    value = [lbl for lbl in kv.findChildren(QLabel) if "660000" in lbl.text()][0]

    column, span = kv._grid.getItemPosition(kv._grid.indexOf(value))[1::2]
    assert (column, span) == (1, 1)
    assert value.minimumWidth() >= value.fontMetrics().horizontalAdvance("66000034D0201077")


def test_a_digest_stays_exactly_what_it_was(qapp):
    """No break opportunities inserted, no ellipsis: what is on screen is what gets copied."""
    kv = c.KeyValueList()
    kv.set_rows([c.Row("Huella", _SHA256, role="mono")])
    value = [lbl for lbl in kv.findChildren(QLabel) if "96ccc622" in lbl.text()][0]
    assert value.text() == _SHA256


def test_an_empty_list_is_not_a_crash(qapp):
    kv = c.KeyValueList()
    kv.set_rows([])
    assert widget_text(kv) == ""


# --- the check list ----------------------------------------------------------

def test_a_check_list_glosses_the_names_it_knows(qapp):
    checks = c.CheckList()
    checks.set_checks([c.CheckItem("PASS", "certificate chain to trusted root")])
    assert "Cadena de certificados" in widget_text(checks)


def test_an_unknown_check_renders_in_english_rather_than_vanishing(qapp):
    """The set differs per format and firmauy can add more, so nothing switches on a name."""
    checks = c.CheckList()
    checks.set_checks([c.CheckItem("PASS", "some future check")])
    assert "some future check" in widget_text(checks)


def test_a_failing_check_shows_how_to_fix_it(qapp):
    checks = c.CheckList()
    checks.set_checks([
        c.CheckItem("PASS", "pcscd running", fix="no debería verse"),
        c.CheckItem("WARN", "pcscd running", "installed but not running",
                    fix="sudo systemctl start pcscd"),
    ])
    text = widget_text(checks)
    assert "sudo systemctl start pcscd" in text
    assert "no debería verse" not in text          # a passing check has nothing to fix
    assert "instalado pero no está corriendo" in text     # the detail is glossed too


def test_every_check_gets_its_own_icon(qapp):
    checks = c.CheckList()
    checks.set_checks([c.CheckItem("PASS", "a"), c.CheckItem("WARN", "b"),
                       c.CheckItem("FAIL", "c")])
    assert [i.status() for i in checks.findChildren(c.StatusIcon)] == ["PASS", "WARN", "FAIL"]


def test_setting_checks_twice_leaves_no_orphans(qapp):
    checks = c.CheckList()
    checks.set_checks([c.CheckItem("PASS", "a"), c.CheckItem("FAIL", "b", fix="x")])
    first = len(checks.findChildren(QLabel))
    for _ in range(5):
        checks.set_checks([c.CheckItem("PASS", "a"), c.CheckItem("FAIL", "b", fix="x")])
    assert len(checks.findChildren(QLabel)) == first


def test_a_truncated_check_list_renders(qapp):
    """firmauy returns early on a failing check, so a real list can be a single row."""
    checks = c.CheckList()
    checks.set_checks([c.CheckItem("WARN", "PC/SC reader detected", "none found")])
    assert "Lector PC/SC detectado" in widget_text(checks)


# --- the verdict -------------------------------------------------------------

def test_the_verdict_says_it_in_spanish_and_says_what_it_means(qapp):
    verdict = c.Verdict()
    verdict.set_indication("INVALID", "No confíes en este archivo.")
    text = widget_text(verdict)
    assert "INVÁLIDO" in text
    assert "No confíes en este archivo." in text


def test_the_verdict_is_readable_without_seeing_colour(qapp):
    """It used to convey its meaning through colour plus one Spanish word, in an unnamed label.
    Word, icon and accessible description now, which is what WCAG 1.4.1 asks."""
    verdict = c.Verdict()
    verdict.set_indication("VALID", "El documento no se modificó.")

    assert verdict.accessibleName() == "Resultado de la verificación"
    assert "VÁLIDO" in verdict.accessibleDescription()
    assert "El documento no se modificó." in verdict.accessibleDescription()
    assert verdict._icon.status() == "VALID"


@pytest.mark.parametrize("indication, tone", [
    ("VALID", "ok"), ("INDETERMINATE", "warn"), ("INVALID", "bad")])
def test_the_verdict_is_toned_by_meaning(qapp, indication, tone):
    verdict = c.Verdict()
    verdict.set_indication(indication)
    assert verdict._word.property("tone") == tone


def test_an_empty_verdict_hides_itself(qapp):
    verdict = c.Verdict()
    assert verdict.isHidden() is True
    verdict.set_indication("VALID")
    assert verdict.isHidden() is False
    verdict.clear()
    assert verdict.isHidden() is True


# --- card and banner ---------------------------------------------------------

def test_a_card_carries_its_title_and_its_content(qapp):
    card = c.Card("Firmante")
    card.add(c.label("PEREZ PEREZ JUAN"))
    text = widget_text(card)
    assert "Firmante" in text
    assert "PEREZ PEREZ JUAN" in text
    assert card.objectName() == "card"      # so the stylesheet can find it


def test_a_banner_is_hidden_until_it_has_something_to_say(qapp):
    banner = c.Banner()
    assert banner.isHidden() is True

    banner.show_message("Los archivos ya firmados son válidos.", tone="ok")
    assert banner.isHidden() is False
    assert banner.property("tone") == "ok"
    assert "válidos" in widget_text(banner)

    banner.clear()
    assert banner.isHidden() is True


# --- the scheme --------------------------------------------------------------

def test_the_icons_inside_a_component_follow_the_scheme(qapp):
    """Their tint is baked into a pixmap, so a scheme change has to repaint them."""
    theme.set_preference("light")
    mark = c.Mark(True)
    light = mark.pixmap().toImage()

    theme.set_preference("dark")
    try:
        assert mark.pixmap().toImage() != light
    finally:
        theme.set_preference("light")


# --- the plumbing ------------------------------------------------------------

def test_clearing_a_layout_destroys_what_was_in_it(qapp):
    holder = QWidget()
    box = QVBoxLayout(holder)
    for _ in range(3):
        box.addWidget(QLabel("x"))
    assert box.count() == 3

    c.clear_layout(box)

    assert box.count() == 0


def test_clearing_reaches_nested_layouts(qapp):
    holder = QWidget()
    outer = QVBoxLayout(holder)
    inner = QVBoxLayout()
    inner.addWidget(QLabel("x"))
    outer.addLayout(inner)

    c.clear_layout(outer)

    assert outer.count() == 0
    assert inner.count() == 0
