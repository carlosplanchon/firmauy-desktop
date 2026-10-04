# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Firmar: choose a file, sign it, and enter the PIN only once the card is ready.

The primary flow is one drop and one button. Everything else folds away, because a person
signing a contract does not need to decide on a timestamping authority to do it.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)

from firmauy_desktop import activity, settings
from firmauy_desktop.backend import (
    BatchSignResult,
    SignResult,
    output_path_for,
    preflight_batch,
    sign_batch,
    sign_file,
)
from firmauy_desktop.dialogs import ask_pin, confirm_batch_conflicts, confirm_overwrite
from firmauy_desktop.labels import unexpected
from firmauy_desktop.pinflow import PinHandshake
from firmauy_desktop.tasks import CardLock, Deadline, TaskRunner
from firmauy_desktop.ui import components as c
from firmauy_desktop.widgets import Collapsible, DropArea, FileListWidget, ValidatorRow

_OWNER = "firmando"

# A batch runs in one card session, so the whole thing is one PIN. The cap is there because
# a stray select-all in a home directory should be refused, not attempted.
_MAX_BATCH = 200

# The label a person reads, and the value firmauy takes.
_SIGN_AS = [
    ("Según el archivo", "auto"),
    ("PDF firmado (PAdES)", "pdf"),
    ("XML firmado (XAdES)", "xml"),
    ("Firma aparte, .p7s (CAdES)", "cades"),
]

_KIND_LABEL = {
    "pades": "PDF firmado (PAdES)",
    "xades": "XML firmado (XAdES)",
    "cades": "Firma aparte (.p7s, CAdES)",
}
_BACKEND_LABEL = {"native": "modo directo (PC/SC)", "pkcs11": "middleware PKCS#11"}


class SignView(c.Screen):
    verify_requested = Signal(str)      # the freshly signed file, for whoever routes screens

    def __init__(self, card: CardLock | None = None) -> None:
        super().__init__(
            "Firmar",
            "Elegí uno o varios documentos y firmalos con tu cédula. Un lote entero va en "
            "una sola sesión de la tarjeta, así que cuesta un solo PIN."
        )
        self._paths: list[str] = []
        self._output_path: str | None = None
        # How many files this run actually sent to firmauy, and how many are done. The total is
        # what survived the pre-flight, not what was dropped: counting the dropped ones would
        # have the bar stop short of the end every time somebody skipped an existing output.
        self._batch_total = 0
        self._batch_done = 0
        # Set from the UI thread, read from the worker between files. A plain flag is all this
        # needs: nothing is coordinated, one side asks and the other answers.
        self._stop = threading.Event()

        # Shared with the other screens that talk to the card when there is a window around them,
        # its own otherwise, so this view still works built on its own.
        self._card = card or CardLock(self)
        self._card.changed.connect(self._on_card_changed)

        self._runner = TaskRunner(self)
        self._runner.finished.connect(self._on_done)
        self._runner.crashed.connect(self._on_crash)
        self._runner.progress.connect(self._on_progress)

        # One handshake for the whole screen, reset before each run. Safe because the runner
        # refuses to start a second signature while one is in flight, so there is never a second
        # worker that could wake up on somebody else's PIN.
        self._pin = PinHandshake(parent=self)
        self._pin.requested.connect(self._ask_pin, Qt.ConnectionType.QueuedConnection)
        self._pin_prompt = "Ingresá el PIN:"       # replaced with the run's real scope at start


        self._drop = DropArea(
            "Arrastrá uno o varios documentos acá\n(PDF, XML o cualquier archivo)",
            multiple=True,
        )
        self._drop.files_selected.connect(self.load_many)
        self.body.addWidget(self._drop)

        self._files = FileListWidget()
        # Eight rows, not 180 points: the point value was a guess about one font at one size, and
        # a 13 point system font turned a list drawn to hold eight files into one holding four.
        self._files.hide()
        self.body.addWidget(self._files)

        self._button = QPushButton("Firmar")
        # The screen's one action. app.qss has carried a "primary" variant since the theme
        # landed and nothing had ever asked for it, so every button on every screen looked
        # equally optional. Blue only while it can be pressed: the disabled rule keeps a
        # primary that cannot run from shouting about it.
        self._button.setProperty("variant", "primary")
        self._button.setEnabled(False)
        self._button.clicked.connect(self._on_sign)
        self.body.addWidget(self._button)

        # Only meaningful for a batch: firmauy checks between files, so with one file there is
        # nothing to stop before. Says "Cancelar" rather than the verify screen's "Dejar de
        # esperar" because this really does stop the work, it just waits out the current file.
        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.hide()
        self.body.addWidget(self._cancel_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._options_panel = self._build_options()
        self.body.addWidget(self._options_panel)

        # Everything this screen says about the run. In one untoned label, "Firmado: /ruta" and
        # "el archivo ya existe" look exactly alike.
        self._status = c.Banner()
        self.body.addWidget(self._status)

        self._progress = c.Progress()
        self.body.addWidget(self._progress)

        # Its own banner rather than a line inside the one above, because it is good news that
        # only ever appears inside bad news and would have to share that message's tone.
        self._survivors = c.Banner()
        self.body.addWidget(self._survivors)

        self._report = c.KeyValueList()
        self.body.addWidget(self._report)

        # The arbiter, before the buttons: a fresh signature is exactly the document the
        # cross-check is about, and the person who signs and sends without passing through
        # Verificar would otherwise never meet it.
        self._report_validator = ValidatorRow()
        self._report_validator.hide()
        self.body.addWidget(self._report_validator)

        # The primary first, then the rest. A blue button sitting between two grey ones reads as
        # one of three choices rather than as the one worth making.
        done_row = QHBoxLayout()
        self._verify_btn = QPushButton("Verificar el archivo firmado")
        self._verify_btn.setToolTip("Lo abre en la pantalla Verificar, sin necesidad de la cédula.")
        # The primary action once there is a signed file: checking your own work is the next
        # thing worth doing, and it costs neither the card nor a PIN.
        self._verify_btn.setProperty("variant", "primary")
        self._verify_btn.clicked.connect(self._request_verify)
        self._verify_btn.hide()
        done_row.addWidget(self._verify_btn)

        self._open_btn = QPushButton("Abrir carpeta")
        self._open_btn.clicked.connect(self._open_folder)
        self._open_btn.hide()
        done_row.addWidget(self._open_btn)

        self._again_btn = QPushButton("Firmar otro archivo")
        self._again_btn.clicked.connect(self._start_over)
        self._again_btn.hide()
        done_row.addWidget(self._again_btn)
        done_row.addStretch()
        self.body.addLayout(done_row)

        self.body.addStretch()

    def _build_options(self) -> Collapsible:
        box = Collapsible("Opciones avanzadas")
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 0)

        self._sign_as = QComboBox()
        for label, value in _SIGN_AS:
            self._sign_as.addItem(label, value)
        self._sign_as.setToolTip(
            "Por defecto la firma va acorde al archivo. Forzá .p7s si la contraparte pide que "
            "el original quede intacto."
        )
        c.add_field(form, "Tipo de firma:", self._sign_as)

        self._output_dir = QLineEdit()
        self._output_dir.setPlaceholderText("junto al original")
        pick = QPushButton("Elegir...")
        pick.clicked.connect(self._pick_output_dir)
        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(self._output_dir)
        output_layout.addWidget(pick)
        c.add_field(form, "Guardar en:", output_row, focus=self._output_dir)

        self._reason = QLineEdit()
        self._reason.setPlaceholderText("por ejemplo: conformidad con el contrato")
        self._reason.setToolTip("Sólo se usa si el archivo termina siendo un PDF.")
        c.add_field(form, "Motivo:", self._reason)

        self._location = QLineEdit()
        self._location.setPlaceholderText("por ejemplo: Montevideo, Uruguay")
        self._location.setToolTip("Sólo se usa si el archivo termina siendo un PDF.")
        c.add_field(form, "Lugar:", self._location)

        self._tsa = QLineEdit()
        self._tsa.setToolTip(
            "Dejalo vacío para usar el de Ajustes. Sellar con tiempo usa internet."
        )
        c.add_field(form, "Sellado de tiempo:", self._tsa)

        self._sign_as.currentIndexChanged.connect(self._update_pdf_fields)
        self._update_pdf_fields()
        box.add_widget(panel)
        return box

    def _update_pdf_fields(self) -> None:
        """Motivo and Lugar go into the PAdES metadata, so they mean nothing anywhere else."""
        applies = self._sign_as.currentData() in ("auto", "pdf")
        self._reason.setEnabled(applies)
        self._location.setEnabled(applies)

    def _pick_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Elegir dónde guardar")
        if folder:
            self._output_dir.setText(folder)

    # --- signing ------------------------------------------------------------

    def load(self, path: str) -> None:
        """Take a file to sign. Public so a menu or another screen can send one."""
        self.load_many([path])

    def load_many(self, paths: list[str]) -> None:
        """Take one file or many. A batch signs in one card session, so it costs one PIN."""
        if self._runner.busy:
            return
        unique = list(dict.fromkeys(paths))     # a person can pick the same file twice
        # Before the refusal below as well as after it. The report describes a run that is over,
        # so leaving it under "son 500 y el máximo es 200" would put a signed file on screen
        # beside a message about files that were never even accepted.
        self._clear_result()
        self._output_path = None        # a new selection is a new run, so Firmar leads again
        if len(unique) > _MAX_BATCH:
            self._status.show_message(
                f"Son {len(unique)} archivos y el máximo es {_MAX_BATCH}. "
                "Probá con menos por vez.",
                tone="warn",
            )
            return
        self._paths = unique
        # Whatever route the file arrived by. The drop area only knew about its own drops.
        self._drop.show_files(unique)
        self._settle_button()
        self._button.setText("Firmar" if len(unique) <= 1 else f"Firmar los {len(unique)}")
        self._hide_done_buttons()
        self._files.set_paths(unique)
        self._files.setVisible(len(unique) > 1)

    def _on_sign(self, *, overwrite: bool = False) -> None:
        if not self._paths:
            return
        # Cleared first: the pre-flight below marks rows as skipped or unusable, and those marks
        # have to outlive this reset rather than be wiped by it.
        self._files.reset_statuses()
        paths, overwrite = self._resolve_conflicts(self._paths, overwrite)
        if not paths:
            return

        # Worked out before the card is touched, and a failure stops here. Falling back to
        # letting firmauy choose would put the signature somewhere other than the folder that
        # was picked, without saying so, and a signed file quietly landing somewhere else is
        # not a smaller problem than not signing.
        output = None
        if len(self._paths) == 1:
            output, why = self._single_output(paths[0], self._output_dir.text().strip() or None,
                                              self._sign_as.currentData())
            if why:
                self._status.show_message(f"No se pudo resolver dónde guardarlo: {why}",
                                          tone="bad")
                return

        if not self._card.acquire(_OWNER):
            self._status.show_message(
                f"La cédula está ocupada ({self._card.owner()}). Esperá a que termine.",
                tone="warn",
            )
            return

        self._pin.reset()
        self._stop.clear()
        options = self._options()
        # Decided by what was dropped, not by what survived the pre-flight. Skipping two of three
        # still leaves a batch: the person is looking at a list, and should keep seeing per-file
        # rows rather than a single-file report for the one that made it through.
        self._batch_total, self._batch_done = len(paths), 0
        self._pin_prompt = _pin_prompt(paths)
        if len(self._paths) == 1:
            options.pop("output_dir", None)     # sign_file takes a full path, not a folder
            options["output"] = output
            started = self._runner.run(sign_file, paths[0], pin_provider=self._pin.provider,
                                       overwrite=overwrite, **options)
        else:
            started = self._runner.run_with_progress(
                sign_batch, paths, pin_provider=self._pin.provider, overwrite=overwrite,
                should_continue=lambda: not self._stop.is_set(), **options)
        if not started:
            self._card.release(_OWNER)
            return                              # already signing

        self._cancel_btn.setEnabled(True)
        self._cancel_btn.setText("Cancelar")
        self._cancel_btn.setVisible(len(self._paths) > 1)
        self._set_busy(True)
        self._hide_done_buttons()
        self._clear_result()
        # A batch counts its files; one file has nothing to count, so the bar just says "still
        # going" rather than inventing a fraction.
        self._progress.start(self._batch_total if len(self._paths) > 1 else 0)
        self._status.show_message("Buscando la cédula en el lector...")

    def _resolve_conflicts(self, paths: list[str], overwrite: bool) -> tuple[list[str], bool]:
        """Ask about outputs that already exist, before the card is ever touched.

        A batch that stops halfway is the failure this avoids, and an existing output is by far
        its likeliest cause. Local stats and a small read per file, bounded by the batch cap.
        """
        if overwrite or len(paths) <= 1:
            return paths, overwrite             # a single file is handled by the retry dialog
        report = preflight_batch(paths, sign_as=self._sign_as.currentData(),
                                 output_dir=self._output_dir.text().strip() or None)
        for path, why in report.problems:
            self._files.set_status(path, "failed", why)
        usable = report.ready + [src for src, _out in report.conflicts]
        if not report.conflicts:
            return usable, overwrite

        answer = confirm_batch_conflicts(self, report.conflicts, len(paths))
        if answer == "cancel":
            self._status.show_message("Cancelado. No se firmó nada.")
            return [], overwrite
        if answer == "skip":
            for src, _out in report.conflicts:
                self._files.set_status(src, "skipped", "ya estaba firmado")
            return report.ready, overwrite
        return usable, True

    def _options(self) -> dict:
        """The settings decide the machine, the panel decides this document.

        Read at the moment of signing, not at construction, so a change in Ajustes takes effect
        on the next signature instead of the next launch.
        """
        options = settings.sign_kwargs(settings.load())
        options["sign_as"] = self._sign_as.currentData()
        options["output_dir"] = self._output_dir.text().strip() or None
        if self._reason.isEnabled():
            options["reason"] = self._reason.text().strip() or None
            options["location"] = self._location.text().strip() or None
        override = self._tsa.text().strip()
        if override:
            options["tsa_url"] = override       # empty leaves the one from Ajustes in place
        return options

    def _single_output(self, path: str, output_dir: str | None,
                       sign_as: str) -> tuple[str | None, str]:
        """Where the one file goes, and why it could not be worked out.

        sign_file takes a full path where sign_batch takes a folder, and the name is asked of
        firmauy rather than worked out here. ``output_dir / Path(path).name`` is the *input's*
        name: it writes a detached signature for ``doc.bin`` as ``doc.bin`` rather than
        ``doc.bin.p7s``, puts CMS inside a file still called ``.pdf`` when CAdES is forced on
        ``contrato.pdf``, and aims a PDF signed into its own folder at the original instead of
        at ``contrato_firmado.pdf``. The batch path has none of this, because sign_batch is
        handed a folder and firmauy names the files.

        (None, "") when no folder was chosen, which is firmauy's decision to make. (None, reason)
        when a folder was chosen and the name could not be worked out, which is a refusal: the
        caller stops before the card, rather than signing into somewhere else in silence.
        """
        if not output_dir:
            return None, ""
        answer = output_path_for(path, sign_as=sign_as, output_dir=output_dir)
        return (answer.value, "") if answer.ok else (None, answer.error or "razón desconocida")

    def _ask_pin(self) -> None:
        """Prompt on the UI thread, once firmauy has confirmed the reader, card and certificate."""
        self._status.show_message("Cédula detectada. Ingresá el PIN.")
        pin = ask_pin(self, prompt=self._pin_prompt)
        if pin:
            self._status.show_message("Firmando...")
        self._pin.provide(pin)

    def _on_cancel(self) -> None:
        """Ask the batch to stop. It finishes the file it is on first, and says so.

        firmauy only checks between files because an output is written whole or not at all, so
        promising an instant stop would be a lie.
        """
        self._stop.set()
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setText("Cancelando...")
        self._status.show_message("Cancelando. Termina el archivo que está firmando y para ahí.")

    def _on_progress(self, item) -> None:
        """Fired after each output is written, so the list only claims what is really on disk.

        Counted here rather than taken from the event: firmauy reports the file, and how far
        along that is belongs to the run, which is the thing that knows how many there were.
        """
        self._files.set_status(item.path, "signed", Path(item.output_path).name)
        self._batch_done += 1
        self._progress.advance(self._batch_done)
        self._status.show_message(
            f"Firmando {self._batch_done} de {self._batch_total}: {Path(item.path).name}")

    def _on_done(self, result) -> None:
        self._card.release(_OWNER)
        self._progress.stop()
        self._set_busy(False)
        self._cancel_btn.hide()
        if isinstance(result, BatchSignResult):
            self._on_batch_done(result)
            return

        if result.ok:
            self._output_path = result.output_path
            self._status.show_message(f"Firmado: {result.output_path}", tone="ok")
            self._report.set_rows(_report_rows(result))
            self._report_validator.show()
            self._open_btn.show()
            self._verify_btn.show()
            self._again_btn.show()
            self._settle_button()
            return

        if result.error_kind == "output_committed":
            # Signed and on disk, with its permissions left to fix. Red and no buttons would say
            # nothing came out of this, and the obvious response to that is to sign it again.
            self._output_path = result.output_path
            self._status.show_message(result.detail, tone="warn")
            self._report_validator.show()
            self._open_btn.show()
            self._verify_btn.show()
            self._again_btn.show()
            self._settle_button()
            return

        self._status.show_message(result.detail, tone="bad")
        if result.error_kind == "output_exists" and confirm_overwrite(self, result.conflict_path):
            self._on_sign(overwrite=True)

    def _on_batch_done(self, result: BatchSignResult) -> None:
        for item in result.items:
            if item.status == "signed":
                self._files.set_status(item.path, "signed", Path(item.output_path).name)
            elif item.status == "warned":
                # Written and on disk. The row says so, and the detail says what is left to do.
                self._files.set_status(item.path, "warned", item.detail)
            elif item.status == "failed":
                self._files.set_status(item.path, "failed", item.detail)

        total = len(result.items)
        if result.ok:
            self._status.show_message(f"Se firmaron los {total} archivos.", tone="ok")
            output = _last_output(result.items)
            if output:
                self._output_path = output
                self._report_validator.show()
                self._open_btn.show()
                self._again_btn.show()
            self._settle_button()
            return

        cancelled = result.error_kind == "cancelled"
        if cancelled and result.signed == 0:
            self._status.show_message("Cancelado. No se firmó nada.")
            return

        if cancelled:
            self._status.show_message(
                f"Cancelado. Se firmaron {result.signed} de {total} archivos.", tone="warn")
        else:
            self._status.show_message(
                f"Se firmaron {result.signed} de {total} archivos. {result.error}", tone="bad")
        # Never rolled back and never left unsaid: what was written stays written, and this
        # sentence is the difference between trusting the app and panicking. It matters just as
        # much after a cancel, where the person chose to stop and needs to know what was kept.
        #
        # "quedaron guardados", not "son válidos". The self-check that would justify the second
        # is a setting the person can turn off, so what is known here is that the files were
        # written. backend.py says the same thing the same way for the callback case.
        if result.signed:
            self._survivors.show_message(
                "Los archivos ya firmados quedaron guardados.", tone="ok")
        output = _last_output(result.items)
        if output:
            self._output_path = output
            self._report_validator.show()
            self._open_btn.show()
            self._again_btn.show()
        self._settle_button()

    def _on_crash(self) -> None:
        self._card.release(_OWNER)
        self._progress.stop()
        self._set_busy(False)
        self._cancel_btn.hide()
        self._status.show_message(
            unexpected("La firma", recorded=activity.is_on()),
            tone="bad",
        )

    def _clear_result(self) -> None:
        """Everything the last run left behind. A stale report under a fresh run is the way this
        screen misleads: the rows would describe a file nobody is looking at any more."""
        self._status.clear()
        self._survivors.clear()
        self._report.clear()

    def _start_over(self) -> None:
        """Back to an empty screen, which is the only way the button becomes the answer again."""
        self._paths = []
        self._output_path = None
        self._drop.reset()
        self._files.clear()
        self._files.hide()
        self._clear_result()
        self._hide_done_buttons()
        self._settle_button()

    def _settle_button(self) -> None:
        """Firmar leads while there is something to sign and nothing has been signed yet.

        After a run it steps down to an ordinary button and stops being enabled: the operation
        is over, the next useful thing is checking the result, and pressing it again would sign
        the same files onto outputs that now exist and meet the replace dialog. It comes back
        with the next selection.
        """
        done = self._output_path is not None
        self._button.setEnabled(bool(self._paths) and not done)
        self._button.setProperty("variant", None if done else "primary")
        c.repolish(self._button)

    def _hide_done_buttons(self) -> None:
        self._report_validator.hide()
        self._open_btn.hide()
        self._verify_btn.hide()
        self._again_btn.hide()

    def _request_verify(self) -> None:
        if self._output_path:
            self.verify_requested.emit(self._output_path)

    def _on_card_changed(self, busy: bool) -> None:
        """Another screen took the card, or gave it back. Only the trigger needs to know."""
        if busy and self._card.owner() != _OWNER:
            self._button.setEnabled(False)
        elif not busy:
            self._settle_button()

    def _set_busy(self, busy: bool) -> None:
        """Lock the inputs while a signature is in flight, so nothing changes mid-operation.

        The options panel too. Every one of them was read at the moment ``run()`` was called, so
        changing the signature type or the output folder halfway cannot alter what is being
        written, and a panel that still accepts edits says otherwise.
        """
        self._drop.setEnabled(not busy)
        self._button.setEnabled(not busy)
        self._options_panel.setEnabled(not busy)

    def shutdown(self, budget: "int | Deadline" = 5000) -> list:
        """Wait for work in flight, so the window can close without destroying a live thread.

        The release comes first: a worker parked on the PIN prompt would otherwise sit there
        until the timeout, and shutdown would give up and leave the thread running. A batch is
        asked to stop for the same reason, so it ends at the next file instead of working
        through the rest of the queue while the window waits.
        """
        self._stop.set()
        self._pin.provide(None)
        return self._runner.shutdown(budget)

    def _open_folder(self) -> None:
        if not self._output_path:
            return
        folder = str(Path(self._output_path).resolve().parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


def _last_output(items) -> str:
    """The newest file this batch actually produced, for the button that opens one.

    "Produced" has to mean here exactly what it means in ``BatchSignResult.signed``, and for a
    while it did not: that property counts a warned item, because warned is written and on disk
    with only its permissions left to fix, while this looked for ``status == "signed"`` alone.
    Two readings of one word, and both were reachable.

    A batch whose only survivor was warned crashed the screen: `signed` said one, the search
    found none, and a bare ``next()`` raised StopIteration out of a UI slot, where the record
    that exists for unanticipated failures never sees it. Quieter but just as wrong, a batch
    ending [signed, signed, warned] opened the second file while the third sat there newer.

    Returns "" for a batch that produced nothing, so the caller shows no button rather than one
    pointing at an empty path.
    """
    return next((item.output_path for item in reversed(items)
                 if item.status in ("signed", "warned") and item.output_path), "")


def _pin_prompt(paths) -> str:
    """What this PIN authorizes, said by the dialog that asks for it.

    Computed from the batch that is actually about to sign (the survivors of the pre-flight),
    so the prompt and the card session always agree on what one PIN is paying for. A person
    should get to expect that whatever asks for the PIN says what it is for.
    """
    if len(paths) == 1:
        return f"Ingresá el PIN para firmar {Path(paths[0]).name}:"
    return f"Ingresá el PIN para firmar los {len(paths)} archivos:"


def _report_rows(result: SignResult) -> list[c.Row]:
    """What was actually produced. Worth showing: "firmado" alone does not say which of the
    three kinds came out, nor whether the app checked its own work."""
    rows = []
    if result.kind:
        rows.append(c.Row("Tipo", _KIND_LABEL.get(result.kind, result.kind)))
    if result.signer:
        rows.append(c.Row("Firmante", result.signer))
    if result.backend:
        rows.append(c.Row("Backend", _BACKEND_LABEL.get(result.backend, result.backend)))
    if result.certificate_serial:
        rows.append(c.Row("Serie del certificado", result.certificate_serial, role="mono"))
    if result.verified:
        rows.append(c.Row("Comprobada", "sí, se releyó el archivo firmado", mark=True))
    return rows
