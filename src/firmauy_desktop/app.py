# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""FirmaUY Desktop entry point."""

from __future__ import annotations

import os
import sys
from typing import Optional

from PySide6.QtCore import QLibraryInfo, Qt, QTranslator
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QLineEdit

from firmauy_desktop import activity, settings
from firmauy_desktop.main_window import MainWindow
from firmauy_desktop.ui import icons
from firmauy_desktop.ui.theming import theme


def install_qt_translations(app: QApplication, *,
                            folder: Optional[str] = None) -> Optional[QTranslator]:
    """Qt's own words in Spanish, to match the app's.

    Qt draws a few things the app never names: the right-click menu of every text field, a
    standard button nobody gave a label, the file dialog it falls back on when the desktop
    offers none. With no translation loaded those said "Select All" and "Cancel", in English,
    inside an app that is Spanish everywhere else.

    Spanish whatever the system's language, since the app is Spanish whatever it is. And the
    translation only: changing the default QLocale as well would also move the decimal separator
    in the spin boxes in Ajustes. A Qt without its translation files still starts, with English
    menus, which is no reason not to; None says so. ``folder`` is for the tests.

    Parented to the application, which keeps it alive: Qt holds a bare pointer to it.
    """
    translator = QTranslator(app)
    where = folder or QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if not translator.load("qtbase_es", where):
        translator.deleteLater()
        return None
    app.installTranslator(translator)
    return translator


def _selftest_translations() -> int:
    """Load Qt's Spanish and read one of its words back. No GUI, no display.

    The translation is a data file found at run time, the kind of thing a bundle drops without a
    word: the app would start, every screen would still be Spanish, and the menu of every field
    would be back in English, with nothing anywhere to say why.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    translator = install_qt_translations(app)
    field = QLineEdit()
    menu = field.createStandardContextMenu()
    spanish = any(action.text().startswith("Seleccionar todo") for action in menu.actions())
    print(f"selftest-translations: qtbase_es {'cargado' if translator else 'no encontrado'}, "
          f"menú de un campo {'en castellano' if spanish else 'en inglés'}")
    if translator is not None:
        # Left as found, for a caller that shares the application: the suite does.
        app.removeTranslator(translator)
    return 0 if translator is not None and spanish else 1


def _selftest_icons() -> int:
    """Draw every icon and count what came out. No GUI, no display.

    A bundle missing the Qt svg plugin still starts, still builds every screen and simply draws
    nothing where the icons go. Qt raises nothing and logs nothing, so counting pixels is the
    only way to tell a working build from a silently blank one.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QApplication(sys.argv)

    def opaque(image) -> int:
        return sum(1 for x in range(image.width()) for y in range(image.height())
                   if image.pixelColor(x, y).alpha() > 30)

    blank = [name for name in icons.names()
             if opaque(icons.pixmap(name, "fg.default", 16).toImage()) <= 10]
    mark = opaque(icons.app_icon().pixmap(64, 64).toImage())
    print(f"selftest-icons: {len(icons.names())} iconos, {len(blank)} en blanco {blank}, "
          f"marca={mark} pixeles")
    return 1 if blank or mark <= 500 else 0


def _selftest_verify(path: str, expected: str) -> int:
    """Put a real signature through the packed core and exit. No GUI, no card, no display.

    The check the other one cannot make. Starting and drawing every icon says the bundle holds a
    Qt application together, and says nothing about whether it can do the thing it exists for:
    firmauy, pyHanko, cryptography and their plugins are reached by dynamic import and by entry
    point, which is exactly the shape PyInstaller drops quietly.

    ``expected`` is the whole reason this takes an argument at all. The obvious version would
    demand VALID, and CI cannot produce a file that earns it: a synthetic signature cannot reach
    the national anchors, which are pinned by fingerprint, and a real one would mean a document
    signed with somebody's cédula living in the repository. The way out is not to hand this an
    anchor of its own. Naming the anchors for a signer's chain is the option SECURITY.md refuses
    to offer, because a build that accepts a certificate authority turns "install this
    certificate" into a forged signature rendering as VÁLIDO, and it stays refused in the shipped
    binary rather than being let in through a flag nobody was expecting to find there. It is not
    named here either, because the test holding that promise reads this source and cannot tell a
    mention from an offer, which for a security rule is the right way round.

    So CI asserts INDETERMINATE against a generated fixture, which still walks the PDF, the CMS,
    the certificate parsing and the chain building, and stops one step short of a successful
    chain. VALID stays the default, so pointing this at a real signed document still means what
    it says.

    The indication alone would be a poor gate, and that is the point of everything below it.
    INDETERMINATE is where a file this cannot make sense of ends up too, so a bundle that had lost
    the ability to read a signature at all would pass by failing in the expected direction. What
    is asked instead is that exactly one signature was found, that a name was read out of its
    certificate, and that exactly one check failed. Three checks passing and the chain being the
    only casualty is the shape of "everything worked except the thing that cannot work here", and
    it cannot be reached by a verifier that has stopped working.

    None of those name a check or a signer, on purpose. The set of checks differs per format and
    firmauy may add to it, which is why nothing in this app switches on a check name, and the
    fixture's own identity is the fixture's business: the suite asserts who signed it and that it
    reaches VALID against its own authority, because tests may know such things and ship nothing.

    firmauy's API directly rather than through backend.verify_file: that seam maps the report
    onto the dataclasses the screens render and the suite covers it already.
    """
    from firmauy.api import verify

    report = verify(path)
    signatures = list(report.signatures)
    signer = dict(signatures[0].signer) if signatures else {}
    checks = [check for signature in signatures for check in signature.checks]
    failed = [check.name for check in checks if not check.ok]
    passed = [check.name for check in checks if check.ok]
    print(f"selftest-verify: indication={report.indication!r} esperado={expected!r} "
          f"firmas={len(signatures)} firmante={signer.get('common_name')!r} "
          f"pasaron={len(passed)} fallaron={failed!r}")

    if report.indication != expected:
        return 1
    if len(signatures) != 1:
        return 1
    if not signer.get("common_name"):
        return 1
    # A count of failures says nothing about what succeeded. One failing check and nothing else
    # would satisfy it, and that describes a build that found a signature and then did no work on
    # it, which is the shape this whole function exists to catch. So the floor is on the passing
    # side. Measured on the fixture: four checks, three passing, the chain the only casualty.
    #
    # Three is the fixture's shape, which CI owns, and not a property of signatures at large: a
    # detached CMS yields three checks and a XAdES up to ten. Whoever points this at a real
    # document of their own picked the format, so that path asks only that something was checked.
    if len(passed) < (1 if expected == "VALID" else 3):
        return 1
    # None failing for a document that really is valid, exactly one for the fixture, whose chain
    # is the only thing that can fail. Tied to the verdict rather than fixed at one, because a
    # rule that fits the fixture and not a real signed document would only ever be run against
    # the fixture, which is how a gate stops describing anything.
    return 0 if len(failed) == (0 if expected == "VALID" else 1) else 1


def main() -> int:
    # Headless diagnostics: exercise the bundled core and exit, so a frozen build can be
    # validated without a display.
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest-verify":
        return _selftest_verify(sys.argv[2], sys.argv[3] if len(sys.argv) >= 4 else "VALID")

    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest-icons":
        return _selftest_icons()

    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest-translations":
        return _selftest_translations()

    # Must be set before the application object exists. PassThrough is already Qt 6's default and
    # it stays: forcing Round would make this window disagree with every other one on a Windows
    # desktop at 125%, which for a civic tool is worse than a half-pixel border seam. The seams
    # come from hardcoded pixels anyway, and those are moving to the spacing scale.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    # Before anything constructs a QSettings, or Linux writes to ~/.config/Unknown Organization/.
    settings.apply_identity(app)
    app.setApplicationDisplayName(settings.APP)
    # Before the first widget, so nothing Qt draws for it was made with the English words.
    install_qt_translations(app)

    # Fusion, not the native style. The Windows and macOS styles ignore parts of a stylesheet and
    # produce a hybrid that reads as broken rather than as native, and Fusion is the only style
    # present on all three platforms. FIRMAUY_STYLE is the one-line way out if that ever bites.
    app.setStyle(os.environ.get("FIRMAUY_STYLE", "Fusion"))
    stored = settings.load()
    # After apply_identity, never before: the record's location is derived from the application's
    # name, the same way QSettings' is.
    activity.configure(stored.activity_log)
    theme.apply(app, stored.appearance)

    icon = icons.app_icon()   # a missing icon is cosmetic, never a reason not to start
    if not icon.isNull():
        app.setWindowIcon(icon)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
