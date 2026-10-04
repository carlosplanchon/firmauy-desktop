# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Modal prompts.

These are functions rather than methods on the views on purpose: a test replaces the function
and nothing blocks the suite waiting for a click that will never come.

Every box here is plain text, like every label in the app: the values they interpolate are file
names, which on Linux can contain anything at all. Emphasis comes from the split between the
text and its informative text, which QMessageBox already renders as a heading and a body, never
from markup.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import html
from typing import Optional

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QLabel, QLineEdit,
                               QMessageBox, QVBoxLayout, QWidget)

from firmauy_desktop.backend import pin_shape
from firmauy_desktop.ui import components, icons, tokens
from firmauy_desktop.ui.theming import base_point_size


REPO = "https://github.com/carlosplanchon/firmauy-desktop"
# The address SECURITY.md asks people to use, so a problem with the PIN never has to become a
# public issue first. Named here rather than typed into the dialog, so a test can hold the two
# together: the failure mode is Acerca de quietly pointing at an address nobody reads any more.
SECURITY_CONTACT = "carlosplanchon@cognitialabs.com"


def _linked(text: str, *targets: str) -> str:
    """Plain text as HTML, escaped, with each of ``targets`` turned into a link.

    Written this way round on purpose. The caller keeps composing plain text with plain newlines,
    and the escaping happens to all of it in one place, so a value interpolated into that text
    cannot become markup no matter where it came from. Only the exact substrings named here
    become links, so nothing is linkified by guessing.
    """
    marked = html.escape(text).replace("\n", "<br>")
    for target in targets:
        escaped = html.escape(target)
        href = f"mailto:{target}" if "@" in target else target
        marked = marked.replace(escaped, f'<a href="{href}">{escaped}</a>')
    return marked


def _box(parent: Optional[QWidget], title: str, text: str, detail: str = "",
         icon: QMessageBox.Icon = QMessageBox.Icon.Question,
         links: bool = False) -> QMessageBox:
    """A message box. ``links`` renders ``detail`` as HTML so a URL in it can be clicked.

    Off for everyone but Acerca de, and that is the whole point of it being a parameter. The two
    confirmation dialogs put a file's name on screen, and a file is named by whoever sent it: with
    markup enabled, a name is a script tag. Acerca de shows constants and package versions, runs
    its text through :func:`_linked`, which escapes everything before linking anything, and a test
    holds the boundary rather than a habit.
    """
    box = QMessageBox(parent)
    # Never markup, whatever the file is called. The one exception is opt-in and asked for above.
    box.setTextFormat(Qt.TextFormat.RichText if links else Qt.TextFormat.PlainText)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    if detail:
        box.setInformativeText(detail)
    return box


_PIN_RULE = "El PIN de la cédula tiene entre 4 y 8 dígitos."
# Only for what typing more cannot fix. A PIN on its way to four digits is short at every
# keystroke until it is not, and saying so in red each time would be scolding somebody mid-word.
_PIN_PROBLEMS = {
    "not_digits": "Solo números del 0 al 9: el PIN no lleva letras ni otros signos.",
    "long": "Son más de 8 dígitos, y el PIN de la cédula tiene entre 4 y 8.",
}


class _PinDialog(QDialog):
    """The PIN prompt, built here rather than taken from QInputDialog.

    Its prompt names the file about to be signed, and QInputDialog draws a prompt in a label of
    its own left on AutoText. Measured: a file named ``contrato.pdf<br><br><font size=6
    color=red>Tu cédula se bloqueó. Escribí el PUK en vez del PIN.pdf``, a valid name on Linux,
    put that sentence large and red in the one dialog that asks for the PIN. Here the prompt is a
    plain-text label like every other in the app.

    It also says what is wrong with a PIN while it is being typed, and keeps Aceptar off until
    the cédula could take it. What it never does is change what was typed. Dropping a letter or
    the ninth digit as they arrive would send a PIN the person did not type, behind a field that
    shows only dots, and the card counts that as a wrong one.
    """

    def __init__(self, parent: Optional[QWidget], title: str, prompt: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)

        self._field = QLineEdit()
        self._field.setEchoMode(QLineEdit.EchoMode.Password)
        asking = components.label(prompt)
        asking.setBuddy(self._field)
        self._hint = components.label(_PIN_RULE, role="caption", tone="muted")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        # Named here rather than left to Qt's translation, which app.py loads but a Qt without its
        # translation files does not have: then they read OK and Cancel, in the one dialog
        # everybody who signs sees.
        self._ok.setText("Aceptar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(asking)
        layout.addWidget(self._field)
        layout.addWidget(self._hint)
        layout.addWidget(buttons)
        # Wide enough for the longest hint on one line, at whatever size the platform sets type.
        # Left to the layout, the dialog came out narrow enough to wrap two of them, and grew a
        # line taller and back as the hint changed under somebody typing.
        metrics = self._hint.fontMetrics()
        margins = layout.contentsMargins()
        self.setMinimumWidth(max(metrics.horizontalAdvance(text)
                                 for text in (_PIN_RULE, *_PIN_PROBLEMS.values()))
                             + margins.left() + margins.right())

        self._field.textChanged.connect(self._judge)
        self._judge("")

    def _judge(self, typed: str) -> None:
        shape = pin_shape(typed)
        self._ok.setEnabled(shape == "ok")
        problem = _PIN_PROBLEMS.get(shape, "")
        self._hint.setText(problem or _PIN_RULE)
        components.set_tone(self._hint, "bad" if problem else "muted")
        # The hint is the only place that says why Aceptar does nothing, and a screen reader
        # reaching the field would not otherwise read a label that is not its buddy.
        self._field.setAccessibleDescription(problem or _PIN_RULE)

    def pin(self) -> str:
        return self._field.text()


def ask_pin(parent: Optional[QWidget], *, title: str = "PIN de la cédula",
            prompt: str = "Ingresá el PIN:") -> Optional[str]:
    """Ask for the cédula's PIN. Returns None when it is dismissed.

    Nothing here keeps the PIN: it goes straight to the caller, which hands it to the handshake
    and forgets it. The dialog is deleted on the way out rather than left as a child of the
    screen that opened it, where its field would hold the PIN until the window closed.
    """
    dialog = _PinDialog(parent, title, prompt)
    try:
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.pin() if accepted else None
    finally:
        dialog.deleteLater()


def confirm_overwrite(parent: Optional[QWidget], path: str) -> bool:
    """Ask before replacing a file that is already there. True means go ahead.

    Asked at the moment of the collision rather than armed as a checkbox beforehand: the same
    capability, with a safe default, and the person sees the name of what is about to go.
    """
    name = Path(path).name if path else "el archivo firmado"
    box = _box(parent, "Ya existe", f"Ya existe {name}.",
               "¿Lo reemplazo? Vas a tener que ingresar el PIN otra vez.")
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
    # Named here, as everywhere a box has buttons. Qt's translation would say "Sí", where a verb
    # says what happens, like the batch question below; and a Qt without its translation files
    # would say Yes and Cancel.
    box.button(QMessageBox.StandardButton.Yes).setText("Reemplazar")
    box.button(QMessageBox.StandardButton.Cancel).setText("Cancelar")
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    return box.exec() == QMessageBox.StandardButton.Yes


def confirm_batch_conflicts(parent: Optional[QWidget], conflicts: list, total: int) -> str:
    """Ask what to do about outputs that already exist, before the card is touched.

    Returns "overwrite", "skip" or "cancel". Deciding here is what turns the most likely
    mid-batch failure into a question, instead of a signature that stops halfway through.
    """
    names = ", ".join(Path(src).name for src, _out in conflicts[:5])
    if len(conflicts) > 5:
        names += f" y {len(conflicts) - 5} más"
    box = _box(parent, "Ya hay archivos firmados",
               f"{len(conflicts)} de {total} archivos ya tienen una versión firmada.", names)
    replace = box.addButton(f"Reemplazar los {len(conflicts)}",
                            QMessageBox.ButtonRole.DestructiveRole)
    skip = box.addButton(f"Omitir esos {len(conflicts)}", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(skip)
    box.exec()
    clicked = box.clickedButton()
    if clicked is replace:
        return "overwrite"
    if clicked is skip:
        return "skip"
    return "cancel"


# A credit in a dialog, not the legal notice. LICENSE carries the full name and is the notice
# that counts, so this can use the shorter form somebody actually goes by. What must not diverge
# is who and when: a different person or a different year would be wrong, a middle name is not.
#
# The year is when the work was written, not whatever year the app happens to be opened in, which
# is why it is a literal rather than a call to the clock.
COPYRIGHT = "Copyright © 2026 Carlos A. Planchón"


def _version_of(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:            # running from a source tree with nothing installed
        return "desconocida"


def _titled(text: str) -> str:
    """Plain text as a heading, sized by the app's own type scale rather than by a literal."""
    app = QApplication.instance()
    size = (base_point_size(app) if app is not None else 10.0) * tokens.TYPE["title"]
    return f'<span style="font-size: {size:.1f}pt">{html.escape(text)}</span>'


# Enough for the walk to settle from any starting size, and finite so a layout that never
# converges costs a slightly wrong picture rather than a window that never opens.
_FIT_ATTEMPTS = 12


def _tallest_mark(box: QMessageBox) -> int:
    """How tall the mark is allowed to get, whatever the text does.

    There is a font size past which the two cannot be matched at all: QMessageBox caps its own
    width, so beyond that the text stops growing sideways and only grows down, asking for a
    square picture taller than the screen. Measured at a 14pt system font, where the text reaches
    505 points and the dialog will not widen past 800. Half the available height keeps the
    failure graceful, a mark shorter than its text, rather than a dialog nobody can dismiss.
    """
    screen = box.screen() or QApplication.primaryScreen()
    return int(screen.availableGeometry().height() * 0.5) if screen is not None else 400


def _fit_mark_to_text(box: QMessageBox) -> None:
    """Grow the mark until it is as tall as the text beside it.

    QMessageBox offers no way to ask, so the text labels are the ones with no pixmap on them.

    The measurement needs a real layout, and ``adjustSize`` on a dialog that has never been shown
    is not one. Traced on an X11 screen: it alternated between 446 and 230 on every pass and
    never settled, burning all twelve attempts and landing on a good number by luck. Shown with
    ``WA_DontShowOnScreen`` the widget is laid out exactly as it will be, without appearing, and
    the same walk converges in two.

    Iterated rather than done a fixed number of times, because the two sides pull on each other:
    the artwork is nearly square, so a taller mark is a wider one, which narrows the text column
    and makes the text taller again.

    Fails soft, like everything else about this mark: an unexpected layout leaves the size the
    caller already chose rather than dropping the picture or raising.
    """
    box.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    box.show()
    try:
        previous = 0
        for _ in range(_FIT_ATTEMPTS):
            # activate(), not processEvents(): this runs while the dialog is being built, and
            # pumping the event loop there would let anything else run in the middle of it.
            box.layout().activate()
            text_height = sum(label.height() for label in box.findChildren(QLabel)
                              if label.text() and label.pixmap().isNull())
            if text_height <= 0:
                return
            if abs(text_height - previous) <= 1:   # settled: another pass asks for the same
                return
            mark = icons.logo(min(text_height, _tallest_mark(box)))
            if mark.isNull():
                return
            box.setIconPixmap(mark)
            box.adjustSize()
            previous = text_height
    finally:
        box.hide()
        box.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, False)


def about_dialog(parent: Optional[QWidget]) -> None:
    """Who made this and which versions are running.

    It said the second half only: the licence was named and the person who holds the copyright
    on it was not, even though every source file in the repository carries their name.

    The firmauy version is the one that matters when something goes wrong, since that is where
    the signing and verification actually happen.
    """
    body = (
        # "la cédula", not "la cédula uruguaya". The qualifier belongs in the English texts,
        # which address anybody; this one is written for people in Uruguay, where it is the only
        # cédula there is. It was the single place the Spanish said it.
        # "la cédula de identidad uruguaya" in full here, unlike the screens, which say "la
        # cédula": those are read while holding one, and this is the line somebody quotes when
        # they explain to a third party what the program is.
        "Aplicación de escritorio para firmar y verificar documentos mediante la cédula de "
        "identidad uruguaya.\n\n"
        # Read from the installed packages, never written down. The firmauy one is what matters
        # when something goes wrong, since the signing and the verification happen there.
        f"FirmaUY {_version_of('firmauy')}\n"
        f"PySide6 {PYSIDE_VERSION}\n\n"
        f"{COPYRIGHT}\n"
        "Software libre, licenciado bajo Apache License 2.0.\n\n"
        # Two claims, not one, because they deny different things and only one of them is paired
        # with the README. "No es una aplicación oficial" says this is not a State product, which
        # is the sentence test_theming holds and README.md carries in English. "Ni afiliado ni
        # respaldado" says there is no relationship behind it either, which is the wording
        # firmauy's own README uses.
        #
        # "del Estado uruguayo", not just "del Estado", and deliberately unlike "la cédula" on
        # the screens: there the qualifier is redundant because the reader is holding the thing.
        # Here the sentence denies a relationship with one particular institution, and "el
        # Estado" on its own can be read as the idea rather than as Uruguay's.
        #
        # No form of "certificación" anywhere near this. In a signing app that word points
        # straight at the certificate, which is the cédula's own and is worth what it is worth
        # whatever program produced the signature. What is disclaimed here is the software.
        "Proyecto independiente. No es una aplicación oficial del Estado uruguayo, ni está "
        "afiliado a él ni respaldado por él.\n\n"
        f"{REPO}\n"
        f"Contacto: {SECURITY_CONTACT}"
    )
    box = _box(
        parent,
        "Acerca de FirmaUY Desktop",
        # A title, at the type scale the rest of the app uses for one. QMessageBox draws its main
        # text bold and at body size, which reads as the first line of a paragraph rather than as
        # the name of the thing. Possible at all because this box renders markup, which it does
        # for the links below and nothing else.
        _titled(f"FirmaUY Desktop {_version_of('firmauy-desktop')}"),
        _linked(body, REPO, SECURITY_CONTACT),
        icon=QMessageBox.Icon.Information,
        links=True,
    )
    # One button, named. Left without any, QMessageBox adds an OK of its own when it is shown,
    # in whatever language Qt's translation files are there for. Added before the mark is
    # fitted, so the measuring pass lays out the same box that will be shown.
    box.setStandardButtons(QMessageBox.StandardButton.Close)
    box.button(QMessageBox.StandardButton.Close).setText("Cerrar")
    # Replaces the Information glyph rather than sitting beside it. When the file is missing the
    # pixmap is null, setIconPixmap is skipped, and the glyph _box already set stays.
    mark = icons.logo(150)
    if not mark.isNull():
        box.setIconPixmap(mark)
        _fit_mark_to_text(box)
    box.exec()
