# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Diagnóstico: why the setup does or does not work, and how to repair it.

Three things belong together here because they all answer "why is this not working": the checks
themselves, the readers the machine can see (which is what the reader setting accepts), and
refreshing the national CA certificates, which is the repair action for the CA check.
"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from firmauy_desktop import activity, settings
from firmauy_desktop.backend import DoctorResult, list_readers, refresh_cas, run_doctor
from firmauy_desktop.labels import unexpected
from firmauy_desktop.tasks import CardLock, Deadline, TaskRunner
from firmauy_desktop.ui import components as c
from firmauy_desktop.widgets import Collapsible

_AUTO = "Automático"
_OWNER = "revisando el sistema"


class DoctorView(c.Screen):
    def __init__(self, card: CardLock | None = None) -> None:
        super().__init__(
            "Diagnóstico",
            "Por qué el lector y la cédula funcionan o no, y qué hacer al respecto."
        )
        self._result_data: DoctorResult | None = None
        self._card = card or CardLock(self)
        self._card.changed.connect(self._on_card_changed)

        # Three runners rather than one. The reader list is chained after a diagnosis so the two
        # pcscd calls never overlap, and the CA download is network work that can run alongside.
        self._doctor = TaskRunner(self)
        self._doctor.finished.connect(self._on_checked)
        self._doctor.crashed.connect(self._on_doctor_crash)
        self._readers = TaskRunner(self)
        self._readers.finished.connect(self._on_readers)
        self._cas = TaskRunner(self)
        self._cas.finished.connect(self._on_cas_done)
        self._cas.progress.connect(self._on_cas_progress)
        self._cas.crashed.connect(self._on_cas_crash)


        self._what_to_check = self._build_what_to_check()
        self.body.addWidget(self._what_to_check)
        self.body.addWidget(self._build_results())
        self.body.addWidget(self._build_cas())
        self.body.addStretch()

    # --- building -----------------------------------------------------------

    def _build_what_to_check(self) -> QWidget:
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(0, 0, 0, 0)

        self._reader = QComboBox()
        self._reader.addItem(_AUTO, "")
        self._reader.setToolTip(
            "La lista se llena con los lectores que aparecen al revisar el sistema."
        )
        c.add_field(form, "Lector:", self._reader)

        current = settings.load()
        self._native = QRadioButton("Modo directo (PC/SC)")
        self._pkcs11 = QRadioButton("Middleware PKCS#11")
        self._native.setChecked(current.native)
        self._pkcs11.setChecked(not current.native)
        backends = QWidget()
        row = QHBoxLayout(backends)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._native)
        row.addWidget(self._pkcs11)
        row.addStretch()
        c.add_field(form, "Revisar:", backends)

        # A real muted label rather than a disabled one: a screen reader announces a disabled
        # widget as unavailable, which is not what an explanatory sentence is.
        # Spanning both columns rather than sitting in the value column under an empty
        # label: there is no field for it to name.
        form.addRow(c.Note(
            "Ajustes decide con cuál se firma. Acá podés revisar el otro sin cambiarlo."
        ))
        return box

    def _build_results(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)

        self._button = QPushButton("Revisar el sistema")
        # The screen's one action. app.qss has carried a "primary" variant since the theme
        # landed and nothing had ever asked for it, so every button on every screen looked
        # equally optional. Blue only while it can be pressed: the disabled rule keeps a
        # primary that cannot run from shouting about it.
        self._button.setProperty("variant", "primary")
        self._button.clicked.connect(self._on_check)
        layout.addWidget(self._button)

        # The summary and the evidence, separately. "Todo en orden" is the
        # answer; the checks underneath are why.
        self._status = c.Banner()
        self._status.show_message(
            'Tocá "Revisar el sistema" para diagnosticar el lector y la cédula.')
        layout.addWidget(self._status)

        self._progress = c.Progress()
        layout.addWidget(self._progress)

        self._checks = c.CheckList()
        layout.addWidget(self._checks)

        self._copy_btn = QPushButton("Copiar diagnóstico")
        self._copy_btn.setToolTip(
            "Copia el resultado como texto, para pegarlo si pedís ayuda.\n"
            "Los datos que pueden identificarte no se copian."
        )
        self._copy_btn.clicked.connect(self._copy_report)
        self._copy_btn.hide()
        layout.addWidget(self._copy_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        return box

    def _build_cas(self) -> Collapsible:
        """The repair, folded away until something needs repairing.

        Always open, a healthy diagnosis would sit above a paragraph, a button and room for a
        log about a problem nobody has. The rest of the app already shows the fix when it is
        relevant and folds the machinery when it is not, and this section is no exception.

        Folded, not gated on which check failed: opening it for CA trouble specifically would
        mean switching on a check's name, and labels.py forbids exactly that, since firmauy is
        free to rename or add checks and every name lookup degrades silently the day it does.
        So _on_checked opens it whenever anything needs looking at, and never closes it on
        its own, because a person who unfolded it is allowed to keep it that way.
        """
        self._cas_box = Collapsible("Certificados de confianza")

        self._cas_box.add_widget(c.label(
            "Verificar ya funciona sin internet con los certificados que trae la app. "
            "Esto los vuelve a bajar de AGESIC y del Ministerio del Interior, y es lo que "
            "arregla el chequeo de arriba cuando falla.",
            tone="muted",
        ))

        self._cas_btn = QPushButton("Actualizar certificados")
        self._cas_btn.clicked.connect(self._on_refresh_cas)
        button_row = QWidget()
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addWidget(self._cas_btn)
        button_layout.addStretch()
        self._cas_box.add_widget(button_row)

        self._cas_log = QPlainTextEdit()
        self._cas_log.setReadOnly(True)
        self._cas_log.setMaximumHeight(c.rows_high(self._cas_log, 6))
        self._cas_log.hide()
        self._cas_box.add_widget(self._cas_log)
        return self._cas_box

    # --- diagnosing ---------------------------------------------------------

    def _on_check(self) -> None:
        # The diagnosis and the reader list both talk to pcscd, and the lock covers the pair:
        # it is released once the chained reader list comes back, not when the checks do.
        if not self._card.acquire(_OWNER):
            self._status.show_message(
                f"La cédula está ocupada ({self._card.owner()}). Esperá a que termine.",
                tone="warn",
            )
            return
        options = {
            "native": self._native.isChecked(),
            "reader": self._reader.currentData() or None,
            "pkcs11_lib": settings.load().pkcs11_lib or None,
        }
        if not self._doctor.run(run_doctor, **options):
            self._card.release(_OWNER)
            return                              # already checking
        self._set_busy(True)
        self._reset_copy_button()
        self._checks.clear()
        self._progress.start()
        self._status.show_message("Revisando...")

    def _on_checked(self, result: DoctorResult) -> None:
        # Not re-enabled here. The card lock covers this call and the chained reader list, and it
        # is released when that one comes back, so a button enabled now is a button that answers
        # "la cédula está ocupada". The panel was already frozen for the pair; this was the one
        # control left out of it.
        self._result_data = result
        if result.error:
            self._card.release(_OWNER)
            self._progress.stop()
            self._set_busy(False)
            self._status.show_message(f"Error: {result.error}", tone="bad")
            return
        self._status.show_message(
            "Todo en orden" if result.ok else "Hay algo para revisar",
            tone="ok" if result.ok else "bad",
        )
        if not result.ok:
            # Something needs looking at, so the repair unfolds on its own. Broader than "a CA
            # check failed" on purpose: deciding that would take a check's name, which nothing
            # in this app is allowed to switch on. Never folded back here, either: a person who
            # opened it gets to keep it open through a healthy run.
            self._cas_box.set_expanded(True)
        self._checks.set_checks([
            c.CheckItem(check.status, check.name, check.detail, check.fix)
            for check in result.checks
        ])
        self._copy_btn.show()
        # Now that pcscd has been poked and is free again, fill the reader list.
        self._readers.run(list_readers)

    def _set_busy(self, busy: bool) -> None:
        """Freeze the reader and the backend for the whole chain.

        Both are read once, when run_doctor is started, and the chained reader list runs after
        that. Left live, a result could arrive under controls already showing a different setup,
        so the screen would be answering about one configuration while describing another.
        """
        self._what_to_check.setEnabled(not busy)
        self._button.setEnabled(not busy)

    def _on_card_changed(self, busy: bool) -> None:
        if busy and self._card.owner() != _OWNER:
            self._button.setEnabled(False)
        elif not busy:
            self._button.setEnabled(True)

    def _on_doctor_crash(self) -> None:
        self._card.release(_OWNER)
        self._progress.stop()
        self._set_busy(False)
        self._button.setEnabled(True)
        self._status.show_message(
            unexpected("El diagnóstico", recorded=activity.is_on()),
            tone="bad",
        )

    def _on_readers(self, result) -> None:
        """Repopulate the combo, keeping whatever the user had picked if it is still there."""
        self._card.release(_OWNER)              # the chain is over, pcscd is free
        self._progress.stop()
        self._set_busy(False)
        if not result.ok:
            return                              # the checks above already said what is wrong
        chosen = self._reader.currentData()
        self._reader.clear()
        self._reader.addItem(_AUTO, "")
        for name in result.value:
            self._reader.addItem(name, name)
        if chosen:
            index = self._reader.findData(chosen)
            self._reader.setCurrentIndex(index if index >= 0 else 0)

    # --- the national CAs ---------------------------------------------------

    def _on_refresh_cas(self) -> None:
        if not self._cas.run_with_progress(refresh_cas):
            return                              # already downloading
        self._cas_btn.setEnabled(False)
        self._cas_log.clear()
        self._cas_log.show()
        self._cas_log.appendPlainText("Bajando los certificados...")

    def _on_cas_progress(self, line) -> None:
        self._cas_log.appendPlainText(str(line))

    def _on_cas_done(self, result) -> None:
        self._cas_btn.setEnabled(True)
        if not result.ok:
            self._cas_log.appendPlainText(f"No se pudo: {result.error}")
            return
        self._cas_log.appendPlainText(f"Listo. Quedaron en {result.value.cache_dir}")

    def _on_cas_crash(self) -> None:
        self._cas_btn.setEnabled(True)
        self._cas_log.appendPlainText(
            unexpected(recorded=activity.is_on())
        )

    # --- copying ------------------------------------------------------------

    def _copy_report(self) -> None:
        if self._result_data is None:
            return
        QGuiApplication.clipboard().setText(_as_plain_text(self._result_data))
        self._copy_btn.setText("Copiado")
        self._copy_btn.setEnabled(False)

    def _reset_copy_button(self) -> None:
        """Hidden is not enough. It comes back on the next diagnosis still saying "Copiado" and
        still disabled, so only the first report of a session could ever be copied."""
        self._copy_btn.hide()
        self._copy_btn.setText("Copiar diagnóstico")
        self._copy_btn.setEnabled(True)

    def shutdown(self, budget: "int | Deadline" = 5000) -> list:
        """Wait for work in flight, so the window can close without destroying a live thread."""
        deadline = Deadline(budget) if isinstance(budget, int) else budget
        return [task for runner in (self._doctor, self._readers, self._cas)
                for task in runner.shutdown(deadline)]


def _as_plain_text(result: DoctorResult) -> str:
    """The report as text to paste into a support conversation, with the personal data out.

    firmauy tags each check with whether its detail can carry the cardholder's own data: some
    PKCS#11 modules use the holder's name as the token label. Trusting that tag beats guessing
    from the check's name, which would let a check added later through unredacted. A check
    without the tag counts as sensitive, so an older firmauy costs detail rather than privacy.
    """
    lines = ["FirmaUY Desktop", "ok: sí" if result.ok else "ok: no", ""]
    for check in result.checks:
        detail = check.detail
        if detail and check.sensitive:
            detail = "[oculto: puede identificarte]"
        lines.append(f"[{check.status}] {check.name}" + (f" ({detail})" if detail else ""))
        if check.status != "PASS" and check.fix:
            lines.append(f"    -> {check.fix}")
    return "\n".join(lines)
