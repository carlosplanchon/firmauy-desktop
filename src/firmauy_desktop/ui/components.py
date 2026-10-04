# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""The widgets the screens are built from.

These replaced a module called ``theme.py`` that rendered almost every result the app produces
as HTML inside a QLabel. That meant two things: a stylesheet could not reach any of it, and every
value had to be escaped by hand, because a RichText label renders whatever it is handed and a
signer's common name arrives from a certificate in a file somebody else sent.

The second problem was not ported here, it was **deleted**. Every label these build is
``PlainText``, and a PlainText label cannot be talked into resolving ``file:///etc/passwd`` no
matter what that common name says. There is no escaping left to remember, and no way to forget
it.

Colour comes from the stylesheet through ``role`` and ``tone`` properties, never from a literal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from PySide6 import QtGui
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from firmauy_desktop.labels import (
    check_detail,
    check_fix,
    check_label,
    indication_label,
)
from firmauy_desktop.ui import icons, tokens
from firmauy_desktop.ui.theming import theme


# --- the plumbing -----------------------------------------------------------

def repolish(widget: QWidget) -> None:
    """Make Qt notice a property change.

    Qt resolves a stylesheet once, when a widget is polished, and changing a dynamic property
    afterwards does not restyle it. Every setProperty in this app goes through here for that
    reason.
    """
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_tone(widget: QWidget, tone: str) -> None:
    """The semantic colour role: "muted", "ok", "warn", "bad", "accent", or "" for default."""
    widget.setProperty("tone", tone or None)
    repolish(widget)


def set_role(widget: QWidget, role: str) -> None:
    """The type role: "caption", "body", "subtitle", "title", "verdict", "mono"."""
    widget.setProperty("role", role or None)
    repolish(widget)


def clear_layout(layout: QLayout) -> None:
    """Remove and destroy every child.

    Every container here rebuilds itself in place, and without this the old widgets stay alive
    and stack up invisibly: the label count grows on each update and the layout slowly wanders.
    """
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def label(text: str = "", *, role: str = "body", tone: str = "",
          wrap: bool = True, selectable: bool = False) -> QLabel:
    """A label that is always plain text.

    PlainText is not a default that can be overridden here on purpose: it is what makes the
    escaping problem go away instead of moving.
    """
    made = QLabel(text)
    made.setTextFormat(Qt.TextFormat.PlainText)
    made.setWordWrap(wrap)
    if selectable:
        # People copy certificate serials and digests out of these screens.
        made.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    made.setProperty("role", role or None)
    if tone:
        made.setProperty("tone", tone)
    return made


def plain_tooltip(text: str) -> str:
    """``text`` as a tooltip that shows exactly what it says.

    A tooltip has no text format to set. Qt draws it in a label of its own left on AutoText,
    which renders whatever looks like markup as markup: a file called ``<b>FACTURA</b>
    PAGADA.pdf`` came out with the word in bold, and the line under it pulled up beside it. So
    the text is turned into markup here on purpose, escaped, which leaves Qt nothing to guess.
    WhiteSpacePre because a file name's double space is part of the name.
    """
    return QtGui.Qt.convertFromPlainText(text, Qt.WhiteSpaceMode.WhiteSpacePre)


def add_field(form: QFormLayout, text: str, field: QWidget,
              *, focus: Optional[QWidget] = None) -> QLabel:
    """Add a form row whose label is plain text and is bound to the thing it names.

    Handed a string, QFormLayout builds the label itself, sets it as the field's buddy, and
    leaves it on AutoText. Handed a QLabel, it keeps the format you gave it and drops the buddy
    without saying so. Both measured, because neither is visible from the call site.

    ``focus`` is for the rows whose field is a wrapper holding a control and a button. Without it
    the label names the wrapper, and the input a person actually types into ends up with no name
    at all: found by walking the window for fields that have neither a buddy nor an accessible
    name, which is a check worth more than reading the call sites.
    """
    made = label(text, wrap=False)
    made.setBuddy(focus or field)
    form.addRow(made, field)
    return made


class Note(QLabel):
    """Small print that explains something.

    A real muted label rather than a normal one with ``setEnabled(False)``: a screen reader
    announces a disabled widget as unavailable, which is not what an explanatory sentence is.
    """

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setProperty("role", "caption")
        self.setProperty("tone", "muted")
        # A wrapping label knows its heightForWidth, but a layout only asks when the size policy
        # says to. Without this the height a wrapped note needs is missing from every sizeHint
        # above it: measured, a three-line note in Ajustes left the dialog 48 points short and
        # the layout took them out of the text fields, which came out squeezed to 22 points
        # against a hint of 34. Minimum vertically, so it takes the height it needs and no more.
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        policy.setVerticalPolicy(QSizePolicy.Policy.Minimum)
        self.setSizePolicy(policy)


# --- icons that follow the scheme -------------------------------------------

class _IconLabel(QLabel):
    """A label showing a tinted icon. The tint is baked into the pixmap, so it repaints when the
    scheme changes."""

    def __init__(self, size: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._size = size
        self._name = ""
        self._tone = "fg.default"
        # It only ever holds a pixmap, so this changes nothing it does. It is here so that "no
        # label in this app is left on AutoText" is a claim a test can make about every label it
        # finds, without having to except the ones that happen to be empty today.
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setFixedSize(size, size)
        theme.changed.connect(self._render)

    def _show(self, name: str, tone: str) -> None:
        self._name, self._tone = name, tone
        self._render()

    def _render(self) -> None:
        if not self._name:
            self.clear()
            return
        self.setPixmap(icons.pixmap(self._name, self._tone, self._size,
                                    self.devicePixelRatioF()))


class Mark(_IconLabel):
    """A quiet tick or cross. Nothing at all when the answer is unknown, rather than a placeholder
    that reads as a third state."""

    def __init__(self, state: Optional[bool] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(tokens.ICON["sm"], parent)
        self._state: Optional[bool] = None
        self.set_state(state)

    def state(self) -> Optional[bool]:
        return self._state

    def set_state(self, state: Optional[bool]) -> None:
        self._state = state
        self.setVisible(state is not None)
        if state is None:
            self.clear()
            self.setAccessibleName("")
            return
        # Said out loud as well as drawn. The row it annotates does not repeat the answer in its
        # text, so without this the tick and the cross are the same to a screen reader.
        self.setAccessibleName("sí" if state else "no")
        self._show("check" if state else "cross", "status.ok" if state else "status.bad")


class StatusIcon(_IconLabel):
    """PASS / WARN / FAIL, or VALID / INDETERMINATE / INVALID, as a coloured icon."""

    def __init__(self, status: str = "", *, size: str = "md",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(tokens.ICON[size], parent)
        self._status = ""
        self.set_status(status)

    def status(self) -> str:
        return self._status

    def set_status(self, status: str) -> None:
        self._status = status
        # The check's name and detail read the same whether it passed or failed, so the icon is
        # the only thing carrying the answer. It has to be able to say so.
        self.setAccessibleName(tokens.STATUS_SPOKEN.get(status, status))
        if not status:
            self._show("", "fg.muted")
            return
        tone = tokens.STATUS_TONE.get(status)
        self._show(tokens.STATUS_ICON.get(status, "dot"),
                   f"status.{tone}" if tone else "fg.muted")


# --- the containers ---------------------------------------------------------

@dataclass(frozen=True)
class Row:
    label: str
    value: str
    mark: Optional[bool] = None
    role: str = "body"          # "mono" for a digest or a serial


# How wide a mono value may be and still sit beside its label. Measured in characters of its own
# font rather than in pixels, so it tracks the type scale instead of one screen at one size: forty
# hex characters fit next to a label with the window at its minimum, sixty-four do not.
_MONO_INLINE_CHARS = 40


def _mono_inline_limit(value: QLabel) -> int:
    return value.fontMetrics().horizontalAdvance("0" * _MONO_INLINE_CHARS)


class KeyValueList(QWidget):
    """A block of label / value pairs.

    A grid, not a paragraph of `<br>`, which is the one place this conversion can regress: a grid
    cell does not wrap by itself, so a sha256 or a sixty-character common name would force a
    horizontal scrollbar. Hence the word wrap, the minimum width of one and the stretch on the
    value column.

    A long **name** wraps, because it has spaces. A long digest does not, and that half of the
    risk needs its own answer: see the mono branch in ``set_rows``.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(tokens.SPACE["sm"])
        self._grid.setVerticalSpacing(tokens.SPACE["xs"])
        self._grid.setColumnStretch(1, 1)

    def set_rows(self, rows: Sequence[Row]) -> None:
        clear_layout(self._grid)
        line = 0
        for row in rows:
            name = label(f"{row.label}:", role="body", tone="muted", wrap=False)
            name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self._grid.addWidget(name, line, 0)

            value = label(row.value, role=row.role, selectable=True)
            value.setMinimumWidth(1)        # or the grid refuses to shrink it and scrolls sideways

            if row.role == "mono":
                # Measured: a PlainText label with word wrap never breaks a string that has no
                # spaces in it. A sha256 stays on one line at every width and is simply clipped,
                # which reads as the whole digest. That is worse than a scrollbar, so a mono value
                # always gets a minimum width that fits all of it. The alternatives were rejected
                # for changing the value itself: break opportunities put invisible characters on
                # the clipboard, and eliding makes the label's own text the shortened one.
                value.ensurePolished()      # or the metrics are the default font, not the mono one
                needs = value.fontMetrics().horizontalAdvance(row.value)
                value.setMinimumWidth(needs)

            if row.role == "mono" and needs > _mono_inline_limit(value):
                # Only what cannot fit beside its label escapes to its own line. A card serial is
                # sixteen characters and looks like a mistake down there; a sha256 is sixty-four
                # and has nowhere else to go.
                if line:
                    # Two of these in a row is the realistic case, and with the grid's uniform
                    # spacing each label sits equidistant from the value above it and the one
                    # below, so which one it names stops being obvious. Separate the group.
                    name.setContentsMargins(0, tokens.SPACE["sm"], 0, 0)
                self._grid.addWidget(value, line + 1, 0, 1, 3)
                line += 2
                continue

            self._grid.addWidget(value, line, 1)
            if row.mark is not None:
                # Its own column, so marks line up down the list like a table's last column.
                #
                # Measured alternative, rejected: packing the mark next to the value inside the
                # cell puts it against the text, but a word-wrapping QLabel's sizeHint is a
                # heuristic about aspect ratio rather than the width of its text, so the value
                # collapsed to three narrow lines with half the card empty beside it. The mark
                # looking stranded on a wide screen is a reading column that is too wide, not a
                # mark in the wrong place, and it gets fixed by capping that width.
                mark = Mark(row.mark)
                mark.setAlignment(Qt.AlignmentFlag.AlignTop)
                self._grid.addWidget(mark, line, 2)
            line += 1

    def clear(self) -> None:
        clear_layout(self._grid)


@dataclass(frozen=True)
class CheckItem:
    status: str                 # PASS / WARN / FAIL
    name: str                   # firmauy's raw English name; the row glosses it
    detail: str = ""
    fix: Optional[str] = None


class CheckList(QWidget):
    """One row per verification or diagnostic check.

    Rendered generically on purpose. The set of checks differs per format, a PDF yields four to
    six and a XAdES up to ten, and firmauy is free to add more, so nothing here switches on a
    name: an unknown one shows up in English rather than disappearing.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(tokens.SPACE["sm"])
        self._grid.setVerticalSpacing(tokens.SPACE["sm"])
        self._grid.setColumnStretch(1, 1)

    def set_checks(self, checks: Sequence[CheckItem]) -> None:
        clear_layout(self._grid)
        row = 0
        for check in checks:
            icon = StatusIcon(check.status, size="sm")
            icon.setAlignment(Qt.AlignmentFlag.AlignTop)
            self._grid.addWidget(icon, row, 0)

            text = check_label(check.name)
            if check.detail:
                text += f"  ({check_detail(check.detail)})"
            name = label(text, selectable=True)
            name.setMinimumWidth(1)
            self._grid.addWidget(name, row, 1)
            row += 1

            if check.status != "PASS" and check.fix:
                # Body size, muted rather than small. A fix is "sudo systemctl start pcscd": a
                # thing somebody has to read and type, not a footnote. The tone is what marks it
                # as secondary to the check above it.
                fix = label(check_fix(check.fix), tone="muted", selectable=True)
                fix.setMinimumWidth(1)
                self._grid.addWidget(fix, row, 1)
                row += 1

    def clear(self) -> None:
        clear_layout(self._grid)


class Card(QFrame):
    """A titled surface. What lets a screen have more than one idea on it without becoming a
    wall of text."""

    def __init__(self, title: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._box = QVBoxLayout(self)
        self._box.setContentsMargins(*(tokens.SPACE["md"],) * 4)
        self._box.setSpacing(tokens.SPACE["sm"])
        if title:
            self._box.addWidget(label(title, role="subtitle", wrap=False))

    def add(self, widget: QWidget) -> None:
        self._box.addWidget(widget)

    def add_layout(self, layout: QLayout) -> None:
        """For the cards whose content is a row rather than a stack of widgets."""
        self._box.addLayout(layout)

    def clear(self) -> None:
        clear_layout(self._box)


class Banner(QFrame):
    """One inline message with a tone and an icon.

    Replaces the several copies of a sentence being dumped into whichever label was to hand, and
    gives the important ones (a partial batch's survivors) somewhere that looks deliberate.
    """

    _ICON = {"ok": "check", "warn": "warning", "bad": "cross", "": "dot"}

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("banner")
        row = QHBoxLayout(self)
        row.setContentsMargins(*(tokens.SPACE["sm"],) * 4)
        row.setSpacing(tokens.SPACE["sm"])
        self._icon = _IconLabel(tokens.ICON["md"])
        self._icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addWidget(self._icon)
        self._text = label("", selectable=True)
        self._text.setMinimumWidth(1)
        row.addWidget(self._text, stretch=1)
        self.hide()

    def show_message(self, text: str, *, tone: str = "") -> None:
        self._text.setText(text)
        set_tone(self, tone)
        set_tone(self._text, tone)
        self._icon._show(self._ICON.get(tone, "dot"),
                         f"status.{tone}" if tone in ("ok", "warn", "bad") else "fg.muted")
        self.setVisible(bool(text))

    def clear(self) -> None:
        self._text.clear()
        self.hide()


class Progress(QProgressBar):
    """A quiet bar for work that takes long enough to look stopped.

    Determinate when the total is known and indeterminate otherwise: Qt reads a range of 0 to 0
    as "busy". That is the honest shape for waiting on a reader or on an OCSP responder, where
    there is no fraction to report and inventing one would be a lie about progress.

    No text of its own. The banner above it is already saying what is happening in words, and two
    things saying it at once is one of them being noise.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTextVisible(False)
        self.setFixedHeight(tokens.SPACE["xs"])
        self.hide()

    def start(self, total: int = 0) -> None:
        """``total`` of 0 means "no idea how long", which is most of what this app waits on."""
        self.setRange(0, total)
        self.setValue(0)
        self.show()

    def advance(self, done: int) -> None:
        self.setValue(done)

    def stop(self) -> None:
        self.setValue(self.maximum())
        self.hide()


class Verdict(QWidget):
    """VÁLIDO / INDETERMINADO / INVÁLIDO, and one sentence saying what that means.

    The app's single most important output, so it carries an icon and an accessible name: the
    answer survives both a screen reader and somebody who cannot separate red from green,
    instead of riding on colour plus one Spanish word.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(tokens.SPACE["xs"])

        head = QHBoxLayout()
        head.setSpacing(tokens.SPACE["sm"])
        head.addStretch()
        self._icon = StatusIcon(size="verdict")
        head.addWidget(self._icon)
        self._word = label("", role="verdict", wrap=False)
        head.addWidget(self._word)
        head.addStretch()
        column.addLayout(head)

        self._meaning = label("", role="body", tone="muted")
        self._meaning.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(self._meaning)

        self.setAccessibleName("Resultado de la verificación")
        self.hide()

    def set_indication(self, indication: str, meaning: str = "", *,
                       word: "str | None" = None) -> None:
        # ``word`` overrides the derived label for the one caller that needs it: a batch whose
        # files all agree says "Los 5: VÁLIDOS" with the same icon, tone and sentence machinery.
        word = word if word is not None else indication_label(indication)
        self._icon.set_status(indication)
        self._word.setText(word)
        set_tone(self._word, tokens.STATUS_TONE.get(indication, ""))
        self._meaning.setText(meaning)
        self.setAccessibleDescription(f"{word}. {meaning}" if meaning else word)
        self.setVisible(bool(indication))

    def clear(self) -> None:
        self._word.clear()
        self._meaning.clear()
        self._icon.set_status("")
        self.hide()


# --- the shape of a screen ---------------------------------------------------

# How wide the reading column is allowed to get. Measured rather than picked: a sha256 on its own
# line needs 385 points, a label column and card padding take it to about 520, and body text stops
# being comfortable to read past roughly seventy characters. Past this the screens looked emptier
# the wider the window got, and a KeyValueList mark ended up against the far edge, a tick with
# nothing next to it to be about.
MAX_CONTENT = 720


def rows_high(widget: QWidget, rows: int) -> int:
    """A height in text rows rather than in pixels.

    A number like 120 is a guess about one font at one size: on a 13 point system font it fits
    four files where it was drawn to fit eight.
    """
    widget.ensurePolished()
    return widget.fontMetrics().height() * rows


class Screen(QWidget):
    """The shape every screen has: a title, one line saying what it is for, and a scrolling body.

    A base class rather than a helper each view composes. The scaffolding underneath was copied
    five times, and five copies of a convention is a convention somebody eventually forgets.

    The title repeats what the sidebar already says, on purpose: the sidebar is the window's
    chrome and this is the page. The line under it is the part that was missing everywhere,
    because four of the five screens never said what they were for at all.
    """

    def __init__(self, title: str, explanation: str = "",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        page = QWidget()
        centred = QHBoxLayout(page)
        centred.setContentsMargins(*(tokens.SPACE["xl"],) * 4)
        holder = QWidget()
        holder.setMaximumWidth(MAX_CONTENT)
        # All three of these matter, and the obvious spelling does not work. A maximum width asks
        # for nothing, so with plain stretches on either side the column collapsed to the width of
        # its widest child. The size policy is what makes it want the space, the stretch factor is
        # what hands the space to the column before the spacers, and the spacers still take what
        # is left once the maximum is reached, which is what keeps it centred. Measured at 900,
        # 660 and 400 points wide: 720 centred, then full width, then full width.
        holder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        centred.addStretch(0)
        centred.addWidget(holder, 1)
        centred.addStretch(0)
        scroll.setWidget(page)

        self.body = QVBoxLayout(holder)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(tokens.SPACE["md"])

        # So a screen reader says which of the five you landed on, rather than "panel".
        self.setAccessibleName(title)
        if explanation:
            self.setAccessibleDescription(explanation)

        self.body.addWidget(label(title, role="title", wrap=False))
        if explanation:
            self.body.addWidget(label(explanation, tone="muted"))

    def add(self, widget: QWidget) -> None:
        self.body.addWidget(widget)

    def add_layout(self, layout: QLayout) -> None:
        self.body.addLayout(layout)

    def add_stretch(self) -> None:
        self.body.addStretch()
