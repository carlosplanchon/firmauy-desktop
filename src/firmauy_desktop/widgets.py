# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Shared widgets."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from firmauy_desktop import labels
from firmauy_desktop.ui import components, icons, tokens
from firmauy_desktop.ui.theming import theme


def local_files(urls) -> list[str]:
    """The dropped URLs that are actually files on this machine.

    A drop can carry anything: a remote URL, whose ``toLocalFile()`` is empty, or a folder,
    which would otherwise travel all the way down into firmauy before being rejected.
    """
    paths = []
    for url in urls:
        local = url.toLocalFile()
        if local and Path(local).is_file():
            paths.append(local)
    return paths


class ValidatorRow(QWidget):
    """The pointer to the State validator: two facts, and the button that opens it.

    One widget rather than a convention, because the same row belongs wherever a signed
    document is on screen (a fresh verdict in Verificar, a fresh signature in Firmar), and two
    hand-built copies of one sentence is how they drift apart. The button opens the site and
    nothing else: the document is taken there by the person, in their browser.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE["md"])
        row.addWidget(components.Note(labels.VALIDATOR_NOTE), stretch=1)
        self.button = QPushButton("Abrir firma.gub.uy")
        self.button.setProperty("variant", "quiet")
        self.button.setToolTip(labels.VALIDATOR_TOOLTIP)
        self.button.clicked.connect(self._open)
        row.addWidget(self.button)

    def _open(self) -> None:
        QDesktopServices.openUrl(QUrl(labels.VALIDATOR_URL))


class DropArea(QFrame):
    """A framed area that accepts files, by drag-and-drop or a file picker.

    Emits ``file_selected`` with a path and, when ``multiple``, ``files_selected`` with the
    whole list, so a person who does not drag and drop can still use the button.
    """

    # Exactly one of these fires, decided by `multiple` at construction, so a listener never
    # has to work out whether it is being told the same thing twice.
    file_selected = Signal(str)     # single mode
    files_selected = Signal(list)   # multiple mode

    def __init__(self, prompt: str, *, multiple: bool = False) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("dropArea")
        # Five rows tall rather than 120 points, so the target a file is dropped onto grows
        # with the system font instead of squeezing its own prompt.
        self.setMinimumHeight(components.rows_high(self, 5))
        self._prompt = prompt
        self._multiple = multiple

        self._label = QLabel(prompt)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)

        self._browse = QPushButton("Elegir archivos..." if multiple else "Elegir archivo...")
        self._browse.clicked.connect(self._on_browse)

        # The area itself is the control, and the button inside it is the same control drawn
        # where a mouse can find it. Without this the drop zone was mouse-only: reachable by
        # keyboard through its button, but never announced as the thing files go to.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(self._browse.text().rstrip("."))
        self.setAccessibleDescription(prompt.replace("\n", " "))
        self._browse.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QVBoxLayout(self)
        layout.addWidget(self._label)
        layout.addWidget(self._browse, alignment=Qt.AlignmentFlag.AlignCenter)

    def keyPressEvent(self, event) -> None:
        """Space or Enter opens the picker, which is what a focus ring on a box has to mean.

        The button keeps doing the same thing for a mouse, but it no longer takes focus of its
        own: two adjacent tab stops that open the same dialog is a thing to trip over, not an
        extra way in.
        """
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._on_browse()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_state("over")

    def dragLeaveEvent(self, event) -> None:
        self._set_state("")

    def _set_state(self, state: str) -> None:
        """The stylesheet reads this. Qt does not restyle on a property change by itself, which
        is why the unpolish/polish is not optional."""
        self.setProperty("state", state or None)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_state("")
        paths = local_files(event.mimeData().urls())
        if not paths:
            # A folder, or something that is not on this machine. Say so rather than fail later.
            self._label.setText("Eso no es un archivo. Probá con uno, o con varios.")
            return
        self._set_files(paths)

    def _on_browse(self) -> None:
        if self._multiple:
            paths, _ = QFileDialog.getOpenFileNames(self, "Elegir archivos")
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Elegir archivo")
            paths = [path] if path else []
        if paths:
            self._set_files(paths)

    def show_files(self, paths: list[str]) -> None:
        """Name what is loaded, without claiming it was chosen here.

        Public because a file can arrive from the Archivo menu or from Firmar's "Verificar el
        archivo firmado", and those never went through this widget. Showing the name only when
        the drop area itself produced the selection would draw the same state two different ways
        depending on how the file got there, and let a verdict sit on a screen that names no
        file at all.
        """
        if not paths:
            self.reset()
            return
        first = Path(paths[0])
        if len(paths) == 1:
            # The folder as well as the name. Two contracts called contrato.pdf in two folders
            # are the same word on screen, and this app is about which document is which.
            held = f"{first.name}\n{first.parent}"
        else:
            held = f"{len(paths)} archivos\n{first.parent}"
        self._label.setText(held)
        # Said out loud too. It was set once at construction and never again, so a screen reader
        # on a loaded drop area still read out "arrastrá un archivo acá".
        self.setAccessibleDescription(held.replace("\n", ", "))

    def _set_files(self, paths: list[str]) -> None:
        self.show_files(paths)
        if not self._multiple:
            self.file_selected.emit(paths[0])
            return
        self.files_selected.emit(paths)

    def reset(self) -> None:
        self._label.setText(self._prompt)
        self.setAccessibleDescription(self._prompt.replace("\n", " "))


class Collapsible(QWidget):
    """A titled section that folds away, collapsed by default.

    This is what lets a screen carry every technical detail without a small window exploding:
    the answer stays at the top and the evidence is one click below it, for whoever wants it.
    """

    def __init__(self, title: str, *, expanded: bool = False) -> None:
        super().__init__()
        self._toggle = QToolButton()
        self._toggle.setText(title)
        self._toggle.setCheckable(True)
        # Named, not styled in place: a widget that styles itself is invisible to the theme.
        self._toggle.setObjectName("collapsibleToggle")
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setIconSize(QSize(tokens.ICON["sm"], tokens.ICON["sm"]))
        self._toggle.toggled.connect(self.set_expanded)
        # The tint is baked into the pixmap, so a scheme change has to redraw it.
        theme.changed.connect(self._retint)

        self._content = QWidget()
        self._body = QVBoxLayout(self._content)
        self._body.setContentsMargins(16, 0, 0, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._toggle)
        layout.addWidget(self._content)

        self.set_expanded(expanded)

    def add_widget(self, widget: QWidget) -> None:
        self._body.addWidget(widget)

    def set_expanded(self, on: bool) -> None:
        self._toggle.setChecked(on)
        self._retint()
        self._content.setVisible(on)

    def _retint(self) -> None:
        name = "chevron-down" if self._toggle.isChecked() else "chevron-right"
        self._toggle.setIcon(icons.icon(name, "fg.muted", tokens.ICON["sm"]))

    def is_expanded(self) -> bool:
        return self._toggle.isChecked()


class FileListWidget(QListWidget):
    """The files queued for a batch, each showing what happened to it.

    Rows are keyed by path rather than by index, so a status can be set as results arrive
    without anyone tracking positions.
    """

    # Icon name and colour token per status, plus what a screen reader should say. An emoji
    # inside the row's text would read out as "white heavy check mark" and take no colour.
    _ICON = {
        "pending": ("dot", "fg.faint", "sin firmar"),
        "signed": ("check", "status.ok", "firmado"),
        "warned": ("warning", "status.warn", "firmado, con una advertencia"),
        "failed": ("cross", "status.bad", "falló"),
        "skipped": ("circle", "fg.muted", "omitido"),
    }

    def __init__(self, *, icons: "dict[str, tuple[str, str, str]] | None" = None) -> None:
        super().__init__()
        self.setAlternatingRowColors(True)
        self.setIconSize(QSize(tokens.ICON["sm"], tokens.ICON["sm"]))
        self._paths: list[str] = []
        # The sign vocabulary by default; a screen with statuses of its own passes its own map,
        # which must include "pending": it is what set_paths marks every row as, and the fallback.
        self._icons = dict(icons) if icons else self._ICON

    #: How many files the list shows before it starts scrolling.
    VISIBLE_ROWS = 8

    def set_paths(self, paths: list[str]) -> None:
        self._paths = list(paths)
        self.clear()
        for path in self._paths:
            self.addItem(Path(path).name)
            self._decorate(self.count() - 1, path, "pending", "")
        self._fit()

    def _fit(self) -> None:
        """Height in whole rows of this list, which is not the same as rows of text.

        ``rows_high`` measures the font, and a row here carries an icon and its own padding:
        measured, 14 points of text inside 32 points of row, so eight rows asked of it show
        3.4, with the fourth file of a batch sliced through the middle, which reads as the app
        having lost it rather than as a list that scrolls.

        Set from here rather than by the caller because only a populated list can measure its own
        row, and a caller holding an empty one gets -1 from ``sizeHintForRow``.
        """
        if not self.count():
            return
        row = self.sizeHintForRow(0)
        if row <= 0:
            return
        self.setMaximumHeight(row * self.VISIBLE_ROWS + 2 * self.frameWidth())

    def paths(self) -> list[str]:
        return list(self._paths)

    def set_status(self, path: str, status: str, detail: str = "") -> None:
        try:
            row = self._paths.index(path)
        except ValueError:
            return
        self.item(row).setText(
            f"{Path(path).name}   {detail}" if detail else Path(path).name)
        self._decorate(row, path, status, detail)

    def _decorate(self, row: int, path: str, status: str, detail: str) -> None:
        item = self.item(row)
        name, tone, spoken = self._icons.get(status, self._icons["pending"])
        item.setIcon(icons.icon(name, tone, tokens.ICON["sm"]))
        item.setData(Qt.ItemDataRole.UserRole, status)
        item.setData(Qt.ItemDataRole.AccessibleTextRole,
                     f"{Path(path).name}, {spoken}" + (f", {detail}" if detail else ""))
        # A file name is whatever whoever sent the file called it, and the detail can quote one.
        item.setToolTip(components.plain_tooltip(f"{path}\n{detail}" if detail else path))

    def reset_statuses(self) -> None:
        self.set_paths(self._paths)
