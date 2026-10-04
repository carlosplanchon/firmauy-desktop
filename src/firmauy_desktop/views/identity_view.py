# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Mi cédula: the cardholder's photo and data, read from the card without a PIN.

The second half of the screen has nothing to do with the card: checking a cédula number is
arithmetic, and it is the thing an ordinary person reaches for most often. It does not deserve a
screen of its own, so it lives here, where numbers already are.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from firmauy_desktop import activity, settings
from firmauy_desktop.backend import Identity, IdentityResult, check_ci, ci_digits, read_identity
from firmauy_desktop.labels import unexpected
from firmauy_desktop.tasks import CardLock, Deadline, TaskRunner
from firmauy_desktop.ui import components as c
from firmauy_desktop.widgets import Collapsible

_PHOTO_HEIGHT = 220
_OWNER = "leyendo la cédula"


class IdentityView(c.Screen):
    def __init__(self, card: CardLock | None = None) -> None:
        super().__init__(
            "Mi cédula",
            "Lo que la cédula dice de vos, leído sin PIN."
        )
        # firmauy cannot read the card while a signing session is open on it: both go through
        # pcscd and conflict. Sharing the lock is what keeps that from being one click away.
        self._card = card or CardLock(self)
        self._card.changed.connect(self._on_card_changed)

        self._runner = TaskRunner(self)
        self._runner.finished.connect(self._on_done)
        self._runner.crashed.connect(self._on_crash)
        self._photo: bytes | None = None
        self._source = QPixmap()        # kept, so a scheme or screen change can redraw it


        self._button = QPushButton("Leer mi cédula")
        # The screen's one action. app.qss has carried a "primary" variant since the theme
        # landed and nothing had ever asked for it, so every button on every screen looked
        # equally optional. Blue only while it can be pressed: the disabled rule keeps a
        # primary that cannot run from shouting about it.
        #
        # Only before a read, though: _settle_action() steps it aside once there is a result.
        self._button.setProperty("variant", "primary")
        self._button.clicked.connect(self._on_read)
        self.body.addWidget(self._button)

        self._status = c.Banner()
        self._status.show_message("Poné la cédula en el lector y tocá \"Leer mi cédula\".")
        self.body.addWidget(self._status)

        self._progress = c.Progress()
        self.body.addWidget(self._progress)

        # Photo on the left, data on the right, like the card itself. Inside a real Card, which
        # this layout was already named after without being one: what came off the card is one
        # thing, and a titled surface is how this app groups one thing. On the bare background
        # the photo and the data read as loose widgets, and this is the screen showing somebody
        # their own document.
        row = QHBoxLayout()
        photo_column = QVBoxLayout()
        self._photo_label = QLabel()
        self._photo_label.setAccessibleName("Foto de la cédula")
        # Only ever a pixmap, but set anyway so "no label is on AutoText" holds for every label
        # in the window rather than for every label that happens to carry text.
        self._photo_label.setTextFormat(Qt.TextFormat.PlainText)
        self._photo_label.hide()                # nothing read yet, so nothing to make room for
        self._photo_label.setFixedHeight(_PHOTO_HEIGHT)
        self._photo_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        photo_column.addWidget(self._photo_label)
        photo_column.addStretch()
        row.addLayout(photo_column)

        data_column = QVBoxLayout()
        self._name = c.label("", role="title")
        data_column.addWidget(self._name)
        self._data = c.KeyValueList()
        self._data.setToolTip(
            "El Nº de documento identifica a esta tarjeta y cambia cada vez que la renovás.\n"
            "Tu número de cédula es el mismo toda la vida."
        )
        data_column.addWidget(self._data)
        data_column.addStretch()
        row.addLayout(data_column, stretch=1)

        # Hidden until a read succeeds: an empty titled frame is a box waiting for content, and
        # before the first read there is no content to wait for.
        self._identity_card = c.Card()
        self._identity_card.add_layout(row)
        self._identity_card.hide()
        self.body.addWidget(self._identity_card)

        # Under both columns, not under the photo. The sha256 is 385 points wide on its own line,
        # so as part of the photo column it set that column's width: a 165 point photo sat in a
        # 390 point space and pushed the person's own data most of the way to the right edge,
        # with a hole in the middle of the screen. It describes the photo either way.
        self._photo_meta = c.KeyValueList()
        self.body.addWidget(self._photo_meta)

        # The digest folds away and the dimensions do not. "240 x 320 · 1,8 KB · JPEG" is read at
        # a glance and tells you what "Guardar foto" would write; the sha256 serves one rare
        # errand, checking an exported copy against the card, and sixty-four characters of it is
        # a lot of screen for that.
        self._photo_digest = c.KeyValueList()
        self._digest_box = Collapsible("Huella de la foto")
        self._digest_box.add_widget(self._photo_digest)
        self._digest_box.hide()
        self.body.addWidget(self._digest_box)

        self._save_btn = QPushButton("Guardar foto...")
        self._save_btn.clicked.connect(self._save_photo)
        self._save_btn.hide()
        self.body.addWidget(self._save_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self.body.addWidget(self._build_ci_checker())
        self.body.addStretch()

    def _build_ci_checker(self) -> QGroupBox:
        """One field, no button: what it does follows from how much was typed.

        Needs no card and no internet, so it works for any number, not only the one in the
        reader. It is a consistency check on the digits, which catches a typo and nothing more.
        """
        box = QGroupBox("Verificar un número de cédula")
        layout = QVBoxLayout(box)

        self._ci_input = QLineEdit()
        # The format hint, not a rule: dots and the hyphen reduce away on arrival, so a number
        # pasted as "1.234.567-8" works anyway. The hint spares the person the wondering.
        self._ci_input.setPlaceholderText("Escribí un número de cédula, sin puntos ni guiones")
        # A placeholder is not a label: it disappears the moment somebody types, and a screen
        # reader reaching an empty field with nothing else to go on announces "cuadro de texto".
        self._ci_input.setAccessibleName("Número de cédula a verificar, sin puntos ni guiones")
        self._ci_input.setClearButtonEnabled(True)
        self._ci_input.textChanged.connect(self._on_ci_typed)
        layout.addWidget(self._ci_input)

        self._ci_message = c.Banner()
        layout.addWidget(self._ci_message)

        # A real muted label rather than a disabled one. Greying it out with setEnabled(False)
        # made a screen reader announce an explanatory sentence as unavailable.
        layout.addWidget(c.Note(
            "Comprueba que el dígito verificador cierre. No dice que la persona exista ni que "
            "el documento sea válido."
        ))
        return box

    # --- reading the card ---------------------------------------------------

    def _on_read(self) -> None:
        if not self._card.acquire(_OWNER):
            self._status.show_message(
                f"La cédula está ocupada ({self._card.owner()}). Esperá a que termine.",
                tone="warn",
            )
            return
        options = settings.card_kwargs(settings.load())
        if not self._runner.run(read_identity, **options):
            self._card.release(_OWNER)
            return                              # already reading
        self._button.setEnabled(False)
        self._save_btn.hide()
        self._progress.start()
        self._status.show_message("Leyendo la cédula...")

    def _on_card_changed(self, busy: bool) -> None:
        if busy and self._card.owner() != _OWNER:
            self._button.setEnabled(False)
        elif not busy:
            self._button.setEnabled(True)

    def _on_crash(self) -> None:
        self._card.release(_OWNER)
        self._progress.stop()
        self._button.setEnabled(True)
        self._status.show_message(
            unexpected("La lectura", recorded=activity.is_on()),
            tone="bad",
        )
        self._clear()

    def _on_done(self, result: IdentityResult) -> None:
        self._card.release(_OWNER)
        self._progress.stop()
        self._button.setEnabled(True)
        if not result.ok or result.identity is None:
            self._status.show_message(result.error or "No se pudo leer la cédula.", tone="bad")
            self._clear()
            return

        identity = result.identity
        self._status.clear()
        self._photo = identity.photo
        self._source = QPixmap()
        if identity.photo and self._source.loadFromData(identity.photo):
            self._save_btn.show()
        self._render_photo()
        self._photo_meta.set_rows(_photo_rows(identity))
        digest = _photo_digest_rows(identity)
        self._photo_digest.set_rows(digest)
        self._digest_box.setVisible(bool(digest))
        self._name.setText(identity.full_name or "")
        self._data.set_rows(_data_rows(identity))
        self._identity_card.show()
        self._settle_action(read_ok=True)

    def _settle_action(self, *, read_ok: bool) -> None:
        """The button follows which of the screen's two states it is in.

        Before a read it is the screen's one action: primary, full width. After a successful
        read the task is done and the content is the point, so a full-width blue button sitting
        over somebody's own data kept advertising a step that already happened. It steps aside:
        renamed to what pressing it now means, ordinary variant, its own width on the left.

        One place rather than a line in each handler, so the two states stay something the code
        says instead of something it implies.
        """
        self._button.setText("Volver a leer" if read_ok else "Leer mi cédula")
        self._button.setProperty("variant", None if read_ok else "primary")
        c.repolish(self._button)                # a property change repaints nothing on its own
        self.body.setAlignment(self._button, Qt.AlignmentFlag.AlignLeft if read_ok
                               else Qt.AlignmentFlag(0))

    def _render_photo(self) -> None:
        """Draw the photo as sharply as the card allows, and never bigger than it really is."""
        # Hidden rather than left empty. The box is a fixed 220 points tall, so a card with no
        # photo on it, or no card at all, opened a blank gap the height of a photo and pushed
        # everything below it down for no reason.
        self._photo_label.setVisible(not self._source.isNull())
        if self._source.isNull():
            self._photo_label.clear()
            return
        device, ratio = _photo_scale(self._source.height(), self.devicePixelRatioF())
        scaled = self._source.scaledToHeight(device, Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(ratio)
        self._photo_label.setPixmap(scaled)

    def showEvent(self, event) -> None:
        """devicePixelRatioF only answers for real once the widget is on a screen, and it changes
        again when the window is dragged to a different one."""
        super().showEvent(event)
        self._render_photo()

    def _clear(self) -> None:
        self._photo = None
        self._source = QPixmap()
        self._render_photo()
        self._photo_meta.clear()
        self._photo_digest.clear()
        self._digest_box.hide()
        self._name.clear()
        self._data.clear()
        self._identity_card.hide()
        self._settle_action(read_ok=False)

    def _save_photo(self) -> None:
        if not self._photo:
            return
        suggested = "cedula_foto.jpg"
        path, _ = QFileDialog.getSaveFileName(self, "Guardar foto", suggested, "Imagen JPEG (*.jpg)")
        if not path:
            return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".jpg")
        try:
            target.write_bytes(self._photo)
        except OSError as exc:
            self._status.show_message(f"No se pudo guardar la foto: {exc}", tone="bad")
        else:
            self._status.show_message(f"Foto guardada: {target}", tone="ok")

    # --- the cédula number --------------------------------------------------

    def _on_ci_typed(self, text: str) -> None:
        """Runs on every keystroke, which check_ci is built for: it never raises."""
        # The national written form carries dots and a hyphen ("1.234.567-8") and gets pasted
        # that way, so whatever arrives is reduced to its digits rather than refused. Letters,
        # and digits from other scripts, have nothing to reduce to, so they vanish, and eight
        # is where a cédula ends.
        digits = ci_digits(text)[:8]
        if digits != text:
            kept = len(ci_digits(text[:self._ci_input.cursorPosition()]))
            self._ci_input.setText(digits)
            self._ci_input.setCursorPosition(min(kept, len(digits)))
            return                              # setText re-enters with the clean value
        result = check_ci(text)
        # ok is None while a partial number is being typed, which is neither right nor wrong, so
        # it gets the neutral tone rather than being coloured as a failure.
        tone = {True: "ok", False: "bad"}.get(result.ok, "")
        self._ci_message.show_message(result.message, tone=tone)

    def shutdown(self, budget: "int | Deadline" = 5000) -> list:
        """Wait for work in flight, so the window can close without destroying a live thread."""
        return self._runner.shutdown(budget)


def _photo_scale(source_height: int, dpr: float) -> tuple[int, float]:
    """How many device pixels to render the photo at, and the ratio to stamp on the result.

    This is the one image in the app where sharpness carries meaning, because somebody holds it
    up against the plastic, and two separate things were wrong. Without a device pixel ratio Qt
    took 220 logical points to mean 220 physical pixels, so a HiDPI screen stretched the result.
    And asking for 440 pixels out of a 320 pixel photo is an enlargement that no amount of
    metadata makes sharp.

    So: the photo is never displayed at more points than it has pixels, and within that it is
    rendered at every pixel the card holds, up to what the screen can actually show.

    Arithmetic rather than a method because the interesting cases are HiDPI ones, and a test
    should not need a HiDPI screen in front of it to reach them.
    """
    display = min(_PHOTO_HEIGHT, source_height)
    device = min(round(display * dpr), source_height)
    return device, device / display


def _photo_rows(identity: Identity) -> list[c.Row]:
    """What the photo is, under it. Useful for comparing a saved copy against the card."""
    meta = identity.photo_meta
    if meta is None:
        return []
    parts = []
    if meta.width and meta.height:
        parts.append(f"{meta.width} x {meta.height}")
    if meta.size_bytes:
        parts.append(_human_size(meta.size_bytes))
    if meta.format:
        parts.append(meta.format.upper())      # firmauy reports it lowercase ("jpeg")
    return [c.Row("Foto", " · ".join(parts))] if parts else []


def _photo_digest_rows(identity: Identity) -> list[c.Row]:
    """The digest, on its own, so it can be folded away from the line above it."""
    meta = identity.photo_meta
    return [c.Row("sha256", meta.sha256, role="mono")] if meta and meta.sha256 else []


def _human_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    return f"{size_bytes / 1024:.1f}".replace(".", ",") + " KB"


def _data_rows(identity: Identity) -> list[c.Row]:
    pairs = []
    if identity.id_number:
        # The check digit is arithmetic consistency, not proof of identity, so it stays a quiet
        # mark beside the number rather than a verdict about the person.
        pairs.append(c.Row("Cédula", identity.id_number, mark=identity.id_number_valid))
    if identity.birth_date:
        pairs.append(c.Row("Nacimiento", identity.birth_date))
    if identity.birthplace:
        pairs.append(c.Row("Lugar", identity.birthplace))
    if identity.nationality:
        pairs.append(c.Row("Nacionalidad", identity.nationality))
    # From here down the fields describe the physical card, not the person. The label matches
    # what the card has printed on it, so the two can be compared, and the tooltip below carries
    # the distinction that "documento" alone does not make in everyday Spanish.
    if identity.document_number:
        pairs.append(c.Row("Nº de documento", identity.document_number))
    if identity.issue_date:
        pairs.append(c.Row("Expedida", identity.issue_date))
    if identity.expiry_date:
        pairs.append(c.Row("Vence", identity.expiry_date))
    return pairs
