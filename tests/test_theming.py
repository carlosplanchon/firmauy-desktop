# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the design system.

Most of what a stylesheet does cannot be asserted, so these check the things that can be: that
the palette is legible by the numbers, that the stylesheet actually parses, and that nothing has
quietly gone back to styling itself. A QSS typo is otherwise completely invisible, because Qt
drops the rule it cannot parse without a word.
"""

from __future__ import annotations

import re
from string import Template

import pytest
from PySide6.QtWidgets import QWidget

from firmauy_desktop.main_window import MainWindow
from firmauy_desktop.ui import tokens
from firmauy_desktop.ui.theming import QSS_PATH, theme

SCHEMES = ("light", "dark")

# Foreground on background, and what WCAG asks of each. Body text needs 4.5:1; large text and the
# boundary of a control need 3:1 (1.4.3 and 1.4.11).
_BODY = [
    ("fg.default", "bg.app"), ("fg.default", "bg.surface"), ("fg.default", "bg.sunken"),
    ("fg.muted", "bg.app"), ("fg.muted", "bg.surface"),
    ("fg.on-accent", "accent.default"), ("identity.fg", "identity.default"),
    ("status.ok", "bg.surface"), ("status.warn", "bg.surface"), ("status.bad", "bg.surface"),
    ("status.ok", "status.ok.bg"), ("status.warn", "status.warn.bg"),
    ("status.bad", "status.bad.bg"),
]
_LARGE = [
    ("fg.faint", "bg.surface"), ("accent.default", "bg.surface"), ("accent.default", "bg.app"),
    ("border.focus", "bg.surface"),
    # Against every surface a control can land on, not only a card. Checking border.strong on
    # bg.surface alone is how it shipped at 2.89:1 on the app background, where the radios in
    # Diagnóstico actually live.
    ("border.strong", "bg.surface"), ("border.strong", "bg.app"), ("border.strong", "bg.sunken"),
]


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("fg, bg", _BODY)
def test_body_text_meets_wcag_aa(scheme, fg, bg):
    palette = tokens.palette_for(scheme)
    ratio = tokens.contrast_ratio(palette[fg], palette[bg])
    assert ratio >= 4.5, f"{fg} on {bg} in {scheme} is {ratio:.2f}:1"


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("fg, bg", _LARGE)
def test_large_text_and_control_edges_meet_wcag_aa(scheme, fg, bg):
    palette = tokens.palette_for(scheme)
    ratio = tokens.contrast_ratio(palette[fg], palette[bg])
    assert ratio >= 3.0, f"{fg} on {bg} in {scheme} is {ratio:.2f}:1"


@pytest.mark.parametrize("scheme", SCHEMES)
def test_a_status_never_reads_as_ordinary_text(scheme):
    """The three statuses are distinct from each other and from the body colour, so a coloured
    word always means something.

    Deliberately not asserted by contrast ratio between them: that measures luminance, and green
    and amber can sit at nearly the same luminance while being plainly different colours. Telling
    them apart is what the icon and the Spanish word are for, which is also the answer for
    somebody who cannot separate red from green at all.
    """
    palette = tokens.palette_for(scheme)
    statuses = [palette["status.ok"], palette["status.warn"], palette["status.bad"]]
    assert len(set(statuses)) == 3
    assert palette["fg.default"] not in statuses
    assert palette["fg.muted"] not in statuses


def test_both_schemes_define_the_same_tokens():
    """A token that only exists in light is a stylesheet that only builds in light."""
    assert set(tokens.SCHEMES["light"]) == set(tokens.SCHEMES["dark"])


def test_every_colour_is_a_hex_triplet():
    for scheme, palette in tokens.SCHEMES.items():
        for name, value in palette.items():
            assert re.fullmatch(r"#[0-9a-f]{6}", value), f"{scheme}.{name} = {value}"


# --- the stylesheet ---------------------------------------------------------

def _identifiers(template: Template) -> set[str]:
    """Every name a template refers to, read the way ``substitute`` will read them.

    Unlike the metadata tests this one guards a defect in the product: a `$typo` in the QSS makes
    Qt drop the rule and say nothing.
    """
    return set(template.get_identifiers())


def test_every_token_the_stylesheet_uses_exists():
    """A `$typo` in the QSS is invisible: Qt drops the rule it cannot parse and says nothing.
    substitute() raising at startup is the only thing that makes it visible at all."""
    used = _identifiers(Template(QSS_PATH.read_text(encoding="utf-8")))
    for scheme in SCHEMES:
        available = set(tokens.qss_variables(scheme, 10.0))
        assert used - available == set(), f"missing in {scheme}"


def test_the_stylesheet_builds_for_both_schemes(qapp):
    for scheme in SCHEMES:
        theme.set_preference(scheme)
        built = theme.build_qss()
        assert "$" not in built                 # nothing left unsubstituted
        assert tokens.palette_for(scheme)["accent.default"] in built
    theme.set_preference("light")


def test_no_label_is_left_on_autotext(make_view, qtbot):
    """The invariant that replaces the escaping suite, and the reason that suite could go.

    RichText is the hazard: a QLabel in that mode renders whatever it is handed, and half of what
    this app shows comes out of a certificate in a file somebody else sent. AutoText is the same
    hazard behind a heuristic, because Qt decides for itself whether the text looks like markup.
    PlainText is the only mode where a signer's common name cannot be anything but a name.

    Every label in the window, including the ones QFormLayout builds for itself, which is what
    ``components.add_field`` exists for.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    window = make_view(MainWindow)
    offenders = [
        f"{lbl.textFormat().name}: {lbl.text()[:40]!r}"
        for lbl in window.findChildren(QLabel)
        if lbl.textFormat() != Qt.TextFormat.PlainText
    ]
    assert offenders == []


def test_the_dialogs_are_plain_text_too(qapp):
    """The last place that still built markup and escaped by hand.

    What it interpolates is file names, and a file name on Linux can contain anything, including
    the `<img src="file:///...">` that made this worth caring about in the first place.
    """
    from PySide6.QtCore import Qt

    from firmauy_desktop import dialogs

    hostile = '<img src="file:///etc/passwd">contrato.pdf'
    box = dialogs._box(None, "Ya existe", f"Ya existe {hostile}.", "detalle")

    assert box.textFormat() == Qt.TextFormat.PlainText
    assert hostile in box.text()            # intact, which is the whole claim


def test_no_widget_carries_its_own_stylesheet(make_view, qtbot):
    """The invariant that keeps the design system from decaying back into inline styles. A widget
    that styles itself is invisible to the dark scheme and to every token change after it."""
    window = make_view(MainWindow)
    offenders = [
        f"{type(w).__name__}#{w.objectName()}"
        for w in window.findChildren(QWidget)
        if w.styleSheet()
    ]
    assert offenders == []


# --- the scheme -------------------------------------------------------------

def test_the_type_scale_is_relative_to_the_platform():
    """The verdict used to be a flat 18pt: 2x on a 9pt Windows default and 1.4x on a 13pt macOS
    one. The same screen, visibly different proportions."""
    windows = tokens.type_scale(9.0)
    macos = tokens.type_scale(13.0)
    assert windows["verdict"] / windows["body"] == pytest.approx(1.9, abs=0.06)
    assert macos["verdict"] / macos["body"] == pytest.approx(1.9, abs=0.06)
    assert windows["verdict"] < macos["verdict"]


def test_switching_scheme_changes_the_colours(qapp):
    theme.set_preference("light")
    light = theme.hex("bg.app")
    theme.set_preference("dark")
    assert theme.hex("bg.app") != light
    assert theme.scheme() == "dark"
    theme.set_preference("light")


def test_a_nonsense_preference_falls_back_to_the_system(qapp):
    theme.set_preference("fosforescente")
    assert theme.preference() == "system"
    theme.set_preference("light")


def test_an_unknown_token_raises_rather_than_rendering_wrong(qapp):
    """Silently returning a default colour would ship a screen the wrong colour and nobody would
    know which one."""
    with pytest.raises(KeyError, match="unknown colour token"):
        theme.hex("bg.aplicacion")


def test_the_palette_covers_what_the_stylesheet_cannot(qapp):
    """Text selection and placeholder text have no QSS selector at all."""
    from PySide6.QtGui import QPalette

    palette = theme.build_palette()
    assert palette.color(QPalette.ColorRole.Highlight).isValid()
    assert palette.color(QPalette.ColorRole.PlaceholderText).isValid()
    assert palette.color(QPalette.ColorRole.HighlightedText).name() == theme.hex("fg.on-accent")


def _licence_notice() -> str:
    """The copyright line out of LICENSE, which is the notice that actually counts."""
    from pathlib import Path

    licence = (Path(__file__).resolve().parent.parent / "LICENSE").read_text(encoding="utf-8")
    return next(line.strip() for line in licence.splitlines()
                if line.strip().startswith("Copyright "))


def test_the_about_box_credits_the_author(qapp, monkeypatch):
    """It named the licence and not the person, though every source file carries their name.

    Deliberately not byte-identical to LICENSE. That is the legal notice and carries the full
    name; this is a credit in a dialog and may use the shorter form somebody goes by. What must
    not diverge is who and when, so that is what this checks: same surname, same year. Demanding
    the same string would be a rule invented by a test rather than one anybody needs.
    """
    from firmauy_desktop import dialogs

    shown = {}
    monkeypatch.setattr(dialogs.QMessageBox, "exec", lambda self: shown.update(
        text=self.text(), detail=self.informativeText()) or 0)
    dialogs.about_dialog(None)

    notice = _licence_notice()
    year = notice.split()[1]
    surname = "Planchón"

    assert dialogs.COPYRIGHT in shown["detail"]
    assert year in dialogs.COPYRIGHT, f"the About box says a different year than {notice!r}"
    assert surname in dialogs.COPYRIGHT and surname in notice

    # The licence by the name a person reads, tied to the identifier the packaging declares.
    # "Apache-2.0" is SPDX and belongs in metadata; "Apache License 2.0" is what the licence
    # calls itself and is what a dialog should say. Demanding the SPDX string on screen would be
    # a rule invented by a test, so the check is that both name the same licence.
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    declared = tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["license"]
    assert declared == "Apache-2.0"
    assert "Apache" in shown["detail"] and "2.0" in shown["detail"]
    assert "Software libre" in shown["detail"]


def test_every_source_header_matches_the_licence(qapp):
    """The headers and LICENSE are the legal notice written many times, and those do have to be
    the same string. The About box is not one of them."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    headers = {line for folder in ("src", "tests", "tools")
               for path in (root / folder).rglob("*.py")
               for line in path.read_text(encoding="utf-8").splitlines()[:2]
               if line.startswith("# Copyright")}

    assert headers == {f"# {_licence_notice()}"}


def test_the_spanish_never_qualifies_the_cedula_as_uruguayan(qapp):
    """The English texts say "Uruguayan eID" because they address anybody. The interface is
    written for people in Uruguay, where it is the only cédula there is, and everywhere else in
    the app already says just "la cédula"."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src"
    offenders = []
    for path in root.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "cédula uruguaya" in line and not line.lstrip().startswith("#"):
                offenders.append(f"{path.name}:{number}")
    assert offenders == []


def test_the_about_box_disclaims_the_app_and_not_the_signature(qapp, monkeypatch):
    """"sin certificación oficial" was about the app and read as being about the signatures.

    In a signing app the word "certificación" points straight at the certificate, and the
    signature is made by the cédula with its own: it is worth what it is worth whatever program
    produced it. What is worth disclaiming is that this is not a State application.
    """
    from firmauy_desktop import dialogs

    shown = {}
    monkeypatch.setattr(dialogs.QMessageBox, "exec", lambda self: shown.update(
        detail=self.informativeText()) or 0)
    dialogs.about_dialog(None)

    assert "no es una aplicación oficial del estado uruguayo" in shown["detail"].lower()
    assert "certificación" not in shown["detail"].lower()


def test_the_about_box_points_at_the_site_before_the_repository(qapp, monkeypatch):
    """Somebody who opens Acerca de is far more likely to want the site, with what FirmaUY is and
    where to download it, than the source. Both can be clicked, and the site comes first."""
    from firmauy_desktop import dialogs

    shown = {}
    monkeypatch.setattr(dialogs.QMessageBox, "exec", lambda self: shown.update(
        detail=self.informativeText()) or 0)
    dialogs.about_dialog(None)

    site = f'<a href="{dialogs.WEBSITE}">{dialogs.WEBSITE}</a>'
    repo = f'<a href="{dialogs.REPO}">{dialogs.REPO}</a>'
    assert site in shown["detail"] and repo in shown["detail"]
    assert shown["detail"].index(site) < shown["detail"].index(repo)


def test_the_about_title_does_not_need_the_apps_installed_metadata(qapp, monkeypatch):
    """A frozen build carries no metadata for firmauy-desktop, since PyInstaller copies it only
    for names it finds written out in an importlib.metadata call. Read from there, the title said
    "FirmaUY Desktop desconocida" in every packaged build and 0.1.0 from a checkout, so nothing
    run from source could see it. This is that build, as far as the metadata is concerned:
    firmauy's travels with the bundle and the app's own does not."""
    from firmauy_desktop import __version__, dialogs

    def as_frozen(name):
        if name == "firmauy-desktop":
            raise dialogs.PackageNotFoundError(name)
        return "1.21.1"

    shown = {}
    monkeypatch.setattr(dialogs, "version", as_frozen)
    monkeypatch.setattr(dialogs.QMessageBox, "exec", lambda self: shown.update(
        text=self.text(), detail=self.informativeText()) or 0)
    dialogs.about_dialog(None)

    assert f"FirmaUY Desktop {__version__}" in shown["text"]
    assert "desconocida" not in shown["text"] + shown["detail"]


def test_the_about_box_shows_qts_notice_and_where_its_licences_are(qapp, monkeypatch):
    """The box shows a copyright notice, and the LGPL asks a program that does to show Qt's among
    them, with a pointer to the copies of the LGPL and the GPL that come with it (LGPL-3.0,
    section 4c). Those copies are in the notices file every bundle carries."""
    from firmauy_desktop import dialogs

    shown = {}
    monkeypatch.setattr(dialogs.QMessageBox, "exec", lambda self: shown.update(
        detail=self.informativeText()) or 0)
    dialogs.about_dialog(None)

    assert "The Qt Company" in dialogs.QT_NOTICE
    assert dialogs.QT_NOTICE in shown["detail"]
    assert "LGPL versión 3" in shown["detail"] and "GPL versión 3" in shown["detail"]
    assert dialogs.NOTICES_FILE in shown["detail"]


def test_a_disabled_spin_box_looks_disabled(qapp, qtbot):
    """The stylesheet named QLineEdit and QComboBox and nothing else, so a spin box fell through
    to whatever Fusion draws. Fusion barely dims one, so a control greyed out on purpose still
    read as available beside a combo that plainly did not, and Ajustes shipped exactly that pair
    side by side.

    Measured on the rendered pixels rather than on the rule, because a QSS selector that matches
    nothing fails silently and asserting the stylesheet text would pass either way.
    """
    from firmauy_desktop.settings import Settings
    from firmauy_desktop.views.settings_dialog import SettingsDialog

    theme.apply(qapp)
    dialog = SettingsDialog(Settings())          # no stamp image, so both are disabled
    qtbot.addWidget(dialog)
    dialog.adjustSize()
    dialog._tabs.setCurrentIndex(2)
    dialog.show()
    image = dialog.grab().toImage()

    def rendered(widget) -> str:
        point = widget.mapTo(dialog, widget.rect().center())
        return image.pixelColor(point.x(), point.y()).name()

    sunken = tokens.SCHEMES[theme.scheme()]["bg.sunken"]
    surface = tokens.SCHEMES[theme.scheme()]["bg.surface"]

    assert dialog._stamp_opacity.isEnabled() is False
    assert rendered(dialog._stamp_opacity) == sunken, "a disabled spin box still looks live"
    assert rendered(dialog._stamp_mode) == sunken       # the combo beside it, for comparison
    assert rendered(dialog._stamp_margin) == surface    # and an enabled one, so this can fail


def test_the_about_mark_is_as_tall_as_the_text_beside_it(qapp, monkeypatch):
    """It was a fixed 150 points against a text block of 230, so the picture sat short and the
    dialog looked unbalanced. The height is measured now, which is also what keeps it right when
    a longer sentence or a different platform font changes how tall that text is.
    """
    from PySide6.QtWidgets import QLabel, QMessageBox

    from firmauy_desktop import dialogs

    boxes = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: boxes.append(self) or 0)
    dialogs.about_dialog(None)
    box = boxes[0]
    box.show()
    qapp.processEvents()

    labels = box.findChildren(QLabel)
    mark = next(lbl for lbl in labels if lbl.pixmap() and not lbl.pixmap().isNull())
    text = sum(lbl.height() for lbl in labels
               if lbl.text() and (lbl.pixmap() is None or lbl.pixmap().isNull()))

    assert text > 0
    assert abs(mark.height() - text) <= 2, f"the mark is {mark.height()} against {text} of text"


def test_the_about_title_uses_the_apps_own_type_scale(qapp):
    """A title, not the first line of a paragraph. Tied to the scale the rest of the app uses so
    it moves with the platform's font rather than sitting on a number somebody picked."""
    from firmauy_desktop import dialogs
    from firmauy_desktop.ui import tokens
    from firmauy_desktop.ui.theming import base_point_size

    expected = base_point_size(qapp) * tokens.TYPE["title"]
    marked = dialogs._titled("FirmaUY Desktop 0.1.0")

    assert f"font-size: {expected:.1f}pt" in marked
    assert expected > base_point_size(qapp), "a title has to be bigger than body text"
    # Escaped, like everything else that reaches this box as markup.
    assert "&lt;b&gt;" in dialogs._titled("<b>")


def test_the_about_mark_is_never_taller_than_half_the_screen(qapp, monkeypatch):
    """There is a font size past which the mark and the text cannot be matched: QMessageBox caps
    its own width, so the text stops growing sideways and only grows down, asking for a nearly
    square picture taller than the screen. Measured at a 20pt system font, where the text reaches
    902 points. The ceiling makes that a mark shorter than its text rather than a dialog nobody
    can dismiss.
    """
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QLabel, QMessageBox

    from firmauy_desktop import dialogs

    previous = qapp.font()
    try:
        qapp.setFont(QFont("Sans", 20))
        boxes = []
        monkeypatch.setattr(QMessageBox, "exec", lambda self: boxes.append(self) or 0)
        dialogs.about_dialog(None)
        box = boxes[0]
        box.show()
        qapp.processEvents()

        mark = next(lbl for lbl in box.findChildren(QLabel)
                    if lbl.pixmap() and not lbl.pixmap().isNull())
        available = qapp.primaryScreen().availableGeometry().height()
        assert mark.height() <= available * 0.5 + 1
    finally:
        qapp.setFont(previous)


def test_the_logo_is_decoded_once(qapp):
    """Acerca de asks for several sizes while it works out which matches its text, and decoding
    that PNG costs 4.4 ms against 1.5 ms to scale it. Reading the file each time was most of what
    opening the dialog cost."""
    from firmauy_desktop.ui import icons

    icons._logo_source.cache_clear()
    first = icons._logo_source()
    assert first is not None
    assert icons._logo_source() is first, "the artwork is being decoded again for every size"
    assert icons._logo_source.cache_info().hits >= 1
