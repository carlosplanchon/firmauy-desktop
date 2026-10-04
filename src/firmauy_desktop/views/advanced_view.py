# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Avanzado: what the PKCS#11 module reports about the card.

Hidden unless the person asked for it in Ajustes. Nothing here is needed to sign or to verify:
it exists to answer "what does my middleware actually see", and to hand somebody your public
certificate, which is a real errand.

Saving the certificate looks like it belongs on Mi cédula, and it does not. It comes from
``list_certs``, which is PKCS#11 only: firmauy has no native read for it, and its default module
path is a system-installed middleware. On the direct PC/SC backend the app recommends, there is
no certificate to export at all. So the export is here, on the screen that is about middleware,
because that is the only setup where it works.

The module used is the one configured in Ajustes, not a separate choice, so what this screen
reports is what signing would use.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from firmauy_desktop import activity, settings
from firmauy_desktop.backend import Cert, list_certs, list_tokens
from firmauy_desktop.labels import unexpected
from firmauy_desktop.tasks import CardLock, Deadline, TaskRunner
from firmauy_desktop.ui import components as c
from firmauy_desktop.ui import tokens as ui_tokens

_OWNER = "leyendo el token"


class AdvancedView(c.Screen):
    def __init__(self, card: CardLock | None = None) -> None:
        super().__init__(
            "Avanzado",
            "Lo que ve el módulo PKCS#11 configurado en Ajustes. Firmar en modo directo no "
            "necesita nada de esto."
        )
        self._certs: list[Cert] = []
        self._lib: str | None = None        # the module this reading is about, fixed at its start
        self._card = card or CardLock(self)
        self._card.changed.connect(self._on_card_changed)

        # Chained, so the two calls into the module never overlap.
        self._tokens = TaskRunner(self)
        self._tokens.finished.connect(self._on_tokens)
        self._tokens.crashed.connect(self._on_crash)
        self._certs_runner = TaskRunner(self)
        self._certs_runner.finished.connect(self._on_certs)
        self._certs_runner.crashed.connect(self._on_crash)


        self._module = c.KeyValueList()
        self.body.addWidget(self._module)

        self._button = QPushButton("Leer el token")
        # The screen's one action. app.qss has carried a "primary" variant since the theme
        # landed and nothing had ever asked for it, so every button on every screen looked
        # equally optional. Blue only while it can be pressed: the disabled rule keeps a
        # primary that cannot run from shouting about it.
        self._button.setProperty("variant", "primary")
        self._button.clicked.connect(self._on_read)
        self.body.addWidget(self._button)

        # A message about the reading and the reading itself are different things, and putting
        # them in one label is what made an error and a token look interchangeable.
        self._status = c.Banner()
        self.body.addWidget(self._status)

        self._progress = c.Progress()
        self.body.addWidget(self._progress)

        self._token_list = QWidget()
        self._token_box = QVBoxLayout(self._token_list)
        self._token_box.setContentsMargins(0, 0, 0, 0)
        self._token_box.setSpacing(ui_tokens.SPACE["md"])
        self.body.addWidget(self._token_list)

        self.body.addWidget(self._build_certs())
        self.body.addStretch()

    def _build_certs(self) -> QGroupBox:
        box = QGroupBox("Certificados")
        layout = QVBoxLayout(box)

        # Shown instead of the controls until there is something to put in them. A greyed-out
        # empty combo above a dead button reads as a broken part of the window rather than as one
        # waiting its turn, and it does not say what would fill it.
        self._empty = c.Note("Leé el token para ver sus certificados.")
        layout.addWidget(self._empty)

        self._picker = QComboBox()
        # No label anywhere near it: the group box title is the only context, and a screen reader
        # announces a bare combo as "cuadro combinado".
        self._picker.setAccessibleName("Certificado")
        self._picker.hide()
        self._picker.currentIndexChanged.connect(self._show_cert)
        layout.addWidget(self._picker)

        self._cert = c.KeyValueList()
        layout.addWidget(self._cert)

        self._cert_status = c.Banner()
        layout.addWidget(self._cert_status)

        self._save_btn = QPushButton("Guardar .pem...")
        self._save_btn.setToolTip(
            "Guarda el certificado público, para mandárselo a quien tiene que verificar tus\n"
            "firmas. No incluye la clave privada, que nunca sale de la cédula."
        )
        self._save_btn.clicked.connect(self._save_pem)
        self._save_btn.setEnabled(False)
        self._save_btn.hide()
        layout.addWidget(self._save_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._group = box
        return box

    def _clear_certs(self) -> None:
        self._certs = []
        self._picker.clear()
        self._cert.clear()
        self._cert_status.clear()
        self._save_btn.setEnabled(False)
        self._show_cert_controls(False)

    def _show_cert_controls(self, on: bool) -> None:
        """Swap between the message and the controls.

        Not `box.setEnabled(False)` any more. A disabled group disables its children, and a
        message a person is meant to read would then be announced by a screen reader as
        unavailable, which the accessibility test already refuses.
        """
        self._empty.setVisible(not on)
        self._picker.setVisible(on)
        self._save_btn.setVisible(on)

    # --- reading ------------------------------------------------------------

    def _on_read(self) -> None:
        if not self._card.acquire(_OWNER):
            self._status.show_message(
                f"La cédula está ocupada ({self._card.owner()}). Esperá a que termine.",
                tone="warn",
            )
            return
        # Captured once for the whole chain: read again between the tokens and the certificates,
        # a module accepted in Ajustes in between would have the screen list one module's token
        # beside another module's certificates.
        self._lib = settings.load().pkcs11_lib or None
        lib = self._lib
        if not self._tokens.run(list_tokens, pkcs11_lib=lib):
            self._card.release(_OWNER)
            return
        self._button.setEnabled(False)
        self._module.set_rows([c.Row("Módulo", lib or "el que trae firmauy por defecto")])
        self._show_tokens([])
        # The certificate side too. It is only rebuilt when the chained call comes back, so a
        # second reading that fails at the token step left the previous card's certificate on
        # screen with "Guardar .pem..." still armed, pointing at data from a card that may not
        # be in the reader any more.
        self._clear_certs()
        self._progress.start()
        self._status.show_message("Leyendo...")

    def _on_tokens(self, result) -> None:
        if not result.ok:
            self._card.release(_OWNER)
            self._progress.stop()
            self._button.setEnabled(True)
            self._status.show_message(f"Error: {result.error}", tone="bad")
            return
        self._show_tokens(result.value)
        self._certs_runner.run(list_certs, pkcs11_lib=self._lib, include_pem=True)

    def _show_tokens(self, tokens) -> None:
        c.clear_layout(self._token_box)
        if not tokens:
            self._status.show_message(
                "El módulo no ve ningún token. ¿Está la cédula en el lector?")
            return
        self._status.clear()
        for token in tokens:
            rows = [c.Row("Etiqueta", token.label)]
            if token.model:
                rows.append(c.Row("Modelo", token.model))
            if token.manufacturer:
                rows.append(c.Row("Fabricante", token.manufacturer))
            if token.serial:
                rows.append(c.Row("Serie", token.serial, role="mono"))
            block = c.KeyValueList()
            block.set_rows(rows)
            self._token_box.addWidget(block)

    def _on_certs(self, result) -> None:
        self._card.release(_OWNER)
        self._progress.stop()
        self._button.setEnabled(True)
        self._clear_certs()
        self._certs = list(result.value or [])
        self._show_cert_controls(bool(self._certs))
        self._save_btn.setEnabled(bool(self._certs))
        if not result.ok:
            self._cert_status.show_message(f"Error: {result.error}", tone="bad")
            return
        for cert in self._certs:
            self._picker.addItem(cert.subject_common_name or cert.id or "(sin nombre)")
        self._show_cert(0)

    def _on_crash(self) -> None:
        self._card.release(_OWNER)
        self._progress.stop()
        self._button.setEnabled(True)
        self._status.show_message(
            unexpected("La lectura", recorded=activity.is_on()),
            tone="bad",
        )

    def _on_card_changed(self, busy: bool) -> None:
        if busy and self._card.owner() != _OWNER:
            self._button.setEnabled(False)
        elif not busy:
            self._button.setEnabled(True)

    # --- one certificate ----------------------------------------------------

    def _current(self) -> Cert | None:
        index = self._picker.currentIndex()
        return self._certs[index] if 0 <= index < len(self._certs) else None

    def _show_cert(self, _index: int) -> None:
        cert = self._current()
        if cert is None:
            self._cert.clear()
            return
        rows = [c.Row("ID", cert.id, role="mono"),
                c.Row("Sujeto", cert.subject_common_name)]
        if cert.subject_serial_number:
            rows.append(c.Row("Cédula", cert.subject_serial_number))
        rows += [
            c.Row("Emisor", cert.issuer_common_name),
            c.Row("Serie", cert.certificate_serial, role="mono"),
            c.Row("Vence", cert.not_after),
        ]
        if cert.digital_signature is not None:
            rows.append(c.Row("Uso de firma digital", "sí" if cert.digital_signature else "no",
                              mark=cert.digital_signature))
        self._cert.set_rows(rows)
        self._save_btn.setEnabled(bool(cert.pem))

    def _save_pem(self) -> None:
        cert = self._current()
        if cert is None or not cert.pem:
            return
        stem = (cert.subject_common_name or cert.id or "certificado").replace(" ", "_")
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar el certificado", f"{stem}.pem", "Certificado PEM (*.pem)")
        if not path:
            return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".pem")
        try:
            target.write_text(cert.pem, encoding="ascii")
        except OSError as exc:
            self._cert_status.show_message(f"No se pudo guardar: {exc}", tone="bad")

    def shutdown(self, budget: "int | Deadline" = 5000) -> list:
        """Wait for work in flight, so the window can close without destroying a live thread."""
        deadline = Deadline(budget) if isinstance(budget, int) else budget
        return [task for runner in (self._tokens, self._certs_runner)
                for task in runner.shutdown(deadline)]
