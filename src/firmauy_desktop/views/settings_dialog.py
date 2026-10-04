# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Ajustes: the machine-level choices, the ones that are not about a particular document.

A modal dialog rather than a tab, on two counts. Settings are an occasional interaction with
natural Aceptar and Cancelar semantics that a tab cannot express, and a tab would put them one
click from the Firmar button, which invites fiddling with the backend mid-task.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from firmauy_desktop import activity
from firmauy_desktop import settings as settings_module
from firmauy_desktop.ui import components as c
from firmauy_desktop.ui.theming import theme
from firmauy_desktop.settings import Settings


class SettingsDialog(QDialog):
    """Edits a copy. ``result_settings`` holds the edited values once it is accepted."""

    def __init__(self, current: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ajustes")
        # Five tabs across the top. 460 fit them on this machine's font and left nothing over,
        # so a larger system font ended in squeezed labels or scroll arrows. The main window's
        # own minimum is 720, so a 620 dialog does not outgrow what it opens over.
        self.setMinimumWidth(620)
        self.result_settings = current
        # Kept so accepting the dialog does not wipe the fields it does not show.
        self._current = current

        layout = QVBoxLayout(self)

        # Tabs, so the dialog is as tall as its tallest page instead of as tall as all four
        # stacked. Measured: stacked they asked for 1093 points, which does not fit on a
        # 1920x1080 desktop once the title bar and the task bar are gone, and what falls off the
        # bottom of a dialog is its buttons. The tallest single page is a third of that.
        self._tabs = QTabWidget()
        for page, title in ((self._build_appearance(current), "Apariencia"),
                            (self._build_signing(current), "Firma"),
                            (self._build_stamp(current), "Estampa"),
                            (self._build_verifying(current), "Verificación"),
                            (self._build_activity(current), "Diagnóstico")):
            page.layout().setContentsMargins(12, 12, 12, 12)
            self._tabs.addTab(page, title)
        layout.addWidget(self._tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Guardar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self._on_reject)
        layout.addWidget(buttons)


    def _build_appearance(self, current: Settings) -> QWidget:
        box = QWidget()
        form = QFormLayout(box)
        self._appearance = QComboBox()
        # Masculine, to agree with "Tema:" beside them, not with the group box above
        # ("Apariencia"), which is the wrong noun to look at.
        for label, value in (("Seguir al sistema", "system"), ("Claro", "light"),
                             ("Oscuro", "dark")):
            self._appearance.addItem(label, value)
        index = self._appearance.findData(current.appearance)
        self._appearance.setCurrentIndex(index if index >= 0 else 0)
        # Applied as it changes rather than on Guardar: this is the one setting a person judges
        # by looking at it, and making them accept a dialog to see it is backwards.
        self._appearance.currentIndexChanged.connect(self._on_appearance_changed)
        c.add_field(form, "Tema:", self._appearance)

        # Here rather than in a menu: it is a preference the app remembers, and Ajustes is where
        # the app's preferences live. A checkable item in Herramientas would be two places to
        # configure the same app.
        self._advanced = QCheckBox("Mostrar la pantalla Avanzado")
        self._advanced.setChecked(current.advanced_mode)
        self._advanced.setToolTip(
            "Agrega una pantalla con lo que el módulo PKCS#11 ve en la tarjeta.\n"
            "No hace falta para firmar ni para verificar."
        )
        form.addRow(self._advanced)
        return box

    def _on_appearance_changed(self) -> None:
        theme.set_preference(self._appearance.currentData())

    def _build_signing(self, current: Settings) -> QWidget:
        # A QVBoxLayout holding the form, rather than the form being the box's layout. Measured:
        # a wrapping label added as a spanning form row is given 29 points where it needs 48, so
        # the note below came out clipped and overlapped by the row after it. A form row does not
        # propagate heightForWidth; a box layout does.
        box = QWidget()
        outer = QVBoxLayout(box)
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 0)

        self._native = QRadioButton("Modo directo (PC/SC)")
        self._native.setToolTip(
            "Habla con la cédula directamente. No necesita instalar ningún middleware."
        )
        self._pkcs11 = QRadioButton("Middleware PKCS#11")
        self._pkcs11.setToolTip(
            "Usa un módulo PKCS#11 instalado en el sistema, como el de Gemalto o el de OpenSC."
        )
        self._native.setChecked(current.native)
        self._pkcs11.setChecked(not current.native)
        self._pkcs11.toggled.connect(self._on_backend_changed)
        c.add_field(form, "Cómo firmar:", self._native)
        form.addRow(self._pkcs11)      # spans, since the label above names the pair

        self._lib = QLineEdit(current.pkcs11_lib)
        self._lib.setPlaceholderText("vacío: el que trae firmauy por defecto")
        browse = QPushButton("Examinar...")
        browse.clicked.connect(self._browse_lib)
        self._lib_row = QWidget()
        lib_layout = QHBoxLayout(self._lib_row)
        lib_layout.setContentsMargins(0, 0, 0, 0)
        lib_layout.addWidget(self._lib)
        lib_layout.addWidget(browse)
        c.add_field(form, "Módulo PKCS#11:", self._lib_row, focus=self._lib)

        self._reader = QLineEdit(current.reader)
        self._reader.setPlaceholderText("vacío: detectar automáticamente")
        c.add_field(form, "Lector:", self._reader)

        self._tsa = QLineEdit(current.tsa_url)
        self._tsa.setPlaceholderText("vacío: sin sello de tiempo")
        self._tsa.setToolTip("Una URL de TSA (RFC 3161). Firmar con sello de tiempo usa internet.")
        c.add_field(form, "Sellado de tiempo:", self._tsa)

        # Beside the URL it belongs with: the authority you stamp with is the one somebody has to
        # recognise when they verify. Empty covers the public authorities, whose roots ship with
        # the app. This field exists for the other case, an accredited Uruguayan provider, whose
        # certificate is in no public bundle and arrives with the subscription.
        self._tsa_ca = QLineEdit(current.tsa_ca)
        self._tsa_ca.setPlaceholderText("vacío: usa las raíces públicas incluidas")
        self._tsa_ca.setToolTip(
            "Un PEM con el certificado de la autoridad de sellado, para verificar.\n"
            "Sólo se usa cuando en Verificar activás comprobar de dónde viene el sello."
        )
        # A path to a file, like the module above and the stamp image, so it gets the same button
        # they do. It was the one field of the three that asked somebody to type a path from
        # memory, and this one arrives by email from a provider rather than sitting in a place
        # anybody knows by heart.
        tsa_ca_browse = QPushButton("Examinar...")
        tsa_ca_browse.clicked.connect(self._browse_tsa_ca)
        tsa_ca_row = QWidget()
        tsa_ca_layout = QHBoxLayout(tsa_ca_row)
        tsa_ca_layout.setContentsMargins(0, 0, 0, 0)
        tsa_ca_layout.addWidget(self._tsa_ca)
        tsa_ca_layout.addWidget(tsa_ca_browse)
        c.add_field(form, "Certificado de la TSA:", tsa_ca_row, focus=self._tsa_ca)

        outer.addWidget(panel)

        # Directly under the field it is about. A field that takes any RFC 3161 URL said nothing
        # about what a stamp from one buys, and the answer is not the same for every provider.
        # Ley 18.600 art. 6: "El documento electrónico no hará fe respecto de su fecha, a menos
        # que ésta conste a través de un fechado electrónico otorgado por un prestador de
        # servicios de certificación acreditado." A stamp from anybody else is real cryptographic
        # evidence of when the signature existed, and is not that.
        #
        # No provider is named on purpose: the accredited list belongs to the UCE and can grow,
        # and an app that names two of them today is wrong the day a third is accredited.
        outer.addWidget(c.Note(
            "El sello prueba criptográficamente cuándo existía la firma. Para que además el "
            "documento haga fe de su fecha, la Ley 18.600 pide un prestador acreditado por la "
            "UCE. Con cualquier otro, el sello sirve como evidencia pero no alcanza para eso."
        ))

        # A trust decision does not belong in a tooltip, which nobody hovers before typing a path.
        # Naming an authority moves the moment firmauy judges the signer's certificate at, and that
        # moment is the one thing that can turn an expired or revoked certificate into VÁLIDO
        # (firmauy's timestamp invariant 4).
        outer.addWidget(c.Note(
            "Aceptar una autoridad de sellado hace que el certificado del firmante se juzgue en la "
            "fecha que dice el sello y no en la de hoy, así que una firma hecha con un certificado "
            "vencido o revocado puede dar VÁLIDO. Ese PEM te lo da tu prestador."
        ))

        # firmauy reaches only public addresses unless asked, so a URL cannot send a request into
        # the network the computer sits on. A TSA or a CRL/OCSP mirror inside it is the reason to
        # ask, and the box sits by the TSA because that is the address a person types. The half
        # nobody would guess goes in the note: verifying with revocation follows addresses that
        # come out of certificates in files other people sent, and this lets those in too.
        self._private_network = QCheckBox(
            "Permitir servidores de la red local (TSA o revocación)")
        self._private_network.setChecked(current.allow_private_network)
        outer.addWidget(self._private_network)
        outer.addWidget(c.Note(
            "Sin esto, la app solo se conecta a direcciones públicas, así una URL no puede llevar "
            "un pedido a una máquina de tu red. Marcalo si tu TSA o tu servidor de CRL/OCSP "
            "están en tu red. Mientras esté marcado, verificar con revocación también puede "
            "consultar direcciones de tu red que vengan en el certificado de un archivo ajeno."
        ))

        self._verify_after = QCheckBox("Verificar la firma recién hecha")
        self._verify_after.setChecked(current.verify_after_sign)
        self._verify_after.setToolTip(
            "Vuelve a leer el archivo firmado para confirmar que la firma quedó bien.\n"
            "Es local y rápido, y evita informar una firma que no ocurrió."
        )
        outer.addWidget(self._verify_after)   # a checkbox is its own label

        self._on_backend_changed()
        return box

    # The lines the stamp can print, in the order they are drawn. Each label is the line itself,
    # with what varies in brackets, so the checkbox shows what appears on the page rather than
    # naming a field. "Fecha" told you a date is printed and not that it reads 07/08/2026 14:30.
    # The date format is firmauy's %d/%m/%Y %H:%M, and the document is the certificate's serial
    # rather than the cédula number, which is why the bracket says so.
    _STAMP_LINES = (
        ("_stamp_title", "stamp_title", "Firma electrónica avanzada, UY"),
        ("_stamp_signer", "stamp_signer", "Firmado por: [tu nombre completo]"),
        ("_stamp_document", "stamp_document", "Documento: [la serie del certificado]"),
        ("_stamp_date", "stamp_date", "Fecha: [dd/mm/aaaa hh:mm]"),
        ("_stamp_issuer", "stamp_issuer", "[la autoridad certificadora]"),
    )

    def _build_stamp(self, current: Settings) -> QWidget:
        """What the visible stamp on a signed PDF looks like.

        Here rather than on Firmar, unlike Motivo and Lugar: those are about one document and this
        is about every document. A logo is chosen once.
        """
        box = QWidget()
        outer = QVBoxLayout(box)

        # Three groups, each under its own heading, because flat they read as one list of five
        # unrelated rows. "Separación" says nothing on its own: it is separation from the page
        # edges, and it only means anything under the corner above it. Same for "Cómo se usa" and
        # "Opacidad", which are about the image and nothing else.
        outer.addWidget(c.label("Dónde va en la página", role="subtitle"))
        form = self._stamp_form(outer)

        # Position first: it is the one setting with a wrong answer rather than a taste. The
        # default box reaches 90 points up the page, above a typical bottom margin, so on a
        # document with text to the foot the stamp is drawn over the words. Corners rather than
        # coordinates because firmauy resolves them against the page's real size, so the answer
        # is right on A4, A5, Letter or anything else. A person does not think in PDF points.
        self._stamp_corner = QComboBox()
        for label, value in (("Abajo a la izquierda", "bottom-left"),
                             ("Abajo a la derecha", "bottom-right"),
                             ("Arriba a la izquierda", "top-left"),
                             ("Arriba a la derecha", "top-right")):
            self._stamp_corner.addItem(label, value)
        index = self._stamp_corner.findData(current.stamp_corner)
        self._stamp_corner.setCurrentIndex(index if index >= 0 else 0)
        self._stamp_corner.setToolTip(
            "Dónde se dibuja la estampa en la página. Si te tapa el texto, movela."
        )
        c.add_field(form, "Esquina:", self._stamp_corner)

        self._stamp_margin = QSpinBox()
        self._stamp_margin.setRange(0, settings_module.STAMP_MARGIN_MAX)
        self._stamp_margin.setSuffix(" pt")
        self._stamp_margin.setValue(current.stamp_margin)
        self._stamp_margin.setToolTip("Cuánto se separa de los dos bordes de esa esquina.")
        c.add_field(form, "Separación:", self._stamp_margin)

        outer.addWidget(c.label("Imagen", role="subtitle"))
        form = self._stamp_form(outer)

        self._stamp_image = QLineEdit(current.stamp_image)
        self._stamp_image.setPlaceholderText("vacío: sólo el texto")
        # The two rows below only mean something once there is an image, so the field they depend
        # on decides whether they are live, the same way the mode decides the opacity.
        self._stamp_image.textChanged.connect(self._on_stamp_mode_changed)
        browse = QPushButton("Examinar...")
        browse.clicked.connect(self._browse_stamp_image)
        image_row = QWidget()
        image_layout = QHBoxLayout(image_row)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.addWidget(self._stamp_image)
        image_layout.addWidget(browse)
        c.add_field(form, "Archivo:", image_row, focus=self._stamp_image)

        self._stamp_mode = QComboBox()
        for label, value in (("Detrás del texto", "background"),
                             ("Al costado del texto", "side"),
                             ("Sólo la imagen, sin texto", "only")):
            self._stamp_mode.addItem(label, value)
        index = self._stamp_mode.findData(current.stamp_image_mode)
        self._stamp_mode.setCurrentIndex(index if index >= 0 else 0)
        self._stamp_mode.currentIndexChanged.connect(self._on_stamp_mode_changed)
        c.add_field(form, "Cómo se usa:", self._stamp_mode)

        self._stamp_opacity = QSpinBox()
        self._stamp_opacity.setRange(0, 100)
        self._stamp_opacity.setSuffix(" %")
        # Stored as 0..1 and shown as a percentage, which is the unit people think in. Rounded
        # rather than truncated so a hand-set 0.205 comes back as 21 and not 20.
        self._stamp_opacity.setValue(round(current.stamp_image_opacity * 100))
        self._stamp_opacity.setToolTip("Cuánto se destiñe la imagen cuando va detrás del texto.")
        c.add_field(form, "Opacidad:", self._stamp_opacity)

        outer.addWidget(c.label("Qué muestra la estampa", role="subtitle"))
        for attr, field_name, label in self._STAMP_LINES:
            check = QCheckBox(label)
            check.setChecked(getattr(current, field_name))
            setattr(self, attr, check)
            outer.addWidget(check)

        outer.addWidget(c.Note(
            "La estampa es un dibujo sobre la página, no la firma. Apagar renglones no cambia lo "
            "que se firma ni lo que ve quien verifica: el nombre, la autoridad y la fecha van "
            "dentro de la firma, donde la criptografía los cubre."
        ))
        self._on_stamp_mode_changed()
        return box

    def _stamp_form(self, outer) -> QFormLayout:
        """A form indented under the heading just added, so a row belongs to it by looking."""
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(16, 0, 0, 0)
        outer.addWidget(panel)
        return form

    def _browse_stamp_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Elegir la imagen de la estampa",
                                              filter="Imágenes (*.png *.jpg *.jpeg)")
        if path:
            self._stamp_image.setText(path)

    def _on_stamp_mode_changed(self) -> None:
        """Grey out every control that cannot do anything from here.

        With no image there is no layout to choose and nothing to fade, and those two rows sat
        there live and inert. Opacity only fades a background. And "sólo la imagen" draws no text,
        so there are no lines to pick.
        """
        has_image = bool(self._stamp_image.text().strip())
        mode = self._stamp_mode.currentData()
        self._stamp_mode.setEnabled(has_image)
        self._stamp_opacity.setEnabled(has_image and mode == "background")
        for attr, _, _ in self._STAMP_LINES:
            getattr(self, attr).setEnabled(not (has_image and mode == "only"))

    def _build_verifying(self, current: Settings) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)

        self._revocation = QCheckBox("Consultar si el certificado fue revocado")
        self._revocation.setChecked(current.check_revocation)
        layout.addWidget(self._revocation)

        # The last of the three labels that were disabled purely to render grey. A screen reader
        # announces a disabled widget as unavailable, which is not what an explanation is.
        layout.addWidget(c.Note(
            "Usa internet y puede demorar. Sin esto la verificación es totalmente offline."
        ))
        return box

    def _build_activity(self, current: Settings) -> QWidget:
        """The activity record: off by default, and off writes nothing at all.

        Here rather than on the Diagnóstico screen because it is a machine choice that outlives a
        session, which is what this dialog is for. What the screen already offers is a snapshot to
        copy, and this is the other half: what happened over time, for a problem that needs more
        than one moment to describe.
        """
        box = QWidget()
        outer = QVBoxLayout(box)

        self._activity = QCheckBox("Guardar un registro de actividad")
        self._activity.setChecked(current.activity_log)
        outer.addWidget(self._activity)

        outer.addWidget(c.Note(
            "Sirve para reportar un problema. Guarda qué hizo la app y qué falló, nunca qué "
            "archivo: no anota rutas, ni nombres, ni tu número de documento, ni el PIN. Apagado "
            "no se escribe nada."
        ))

        outer.addWidget(c.label("Dónde se guarda", role="subtitle"))
        path = c.label(str(activity.log_path()), role="caption", selectable=True)
        outer.addWidget(path)

        self._delete_log = QPushButton("Borrar el registro")
        self._delete_log.clicked.connect(self._on_delete_log)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self._delete_log)
        row_layout.addStretch()
        outer.addWidget(row)

        self._log_status = c.Note("")
        outer.addWidget(self._log_status)
        outer.addStretch()
        return box

    def _on_delete_log(self) -> None:
        """Deleting is explicit, and turning the record off does not do it.

        Somebody who reproduced a problem and then switched the setting would otherwise lose the
        very thing they were about to send.

        The unlinking itself belongs to activity rather than here, because the handler holds the
        file open and deleting around it left the record writing into an inode with no name.

        The checkbox is deliberately left alone. This button means "clear what is in there", not
        "stop recording", so with the setting on the record carries on into a file that exists.
        """
        try:
            removed = activity.clear()
        except OSError as exc:
            self._log_status.setText(f"No se pudo borrar: {exc.strerror}")
            return
        self._log_status.setText("Registro borrado." if removed else "No hay nada que borrar.")

    def _on_backend_changed(self) -> None:
        """The module path only means anything on the PKCS#11 path."""
        self._lib_row.setEnabled(self._pkcs11.isChecked())

    def _browse_lib(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Elegir el módulo PKCS#11")
        if path:
            self._lib.setText(path)

    def _browse_tsa_ca(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Elegir el certificado de la TSA",
                                              filter="Certificados (*.pem *.crt *.cer)")
        if path:
            self._tsa_ca.setText(path)

    def _on_reject(self) -> None:
        """Put the appearance back. It is applied live so it can be judged, and a person who
        cancels expects that undone along with everything else."""
        theme.set_preference(self._current.appearance)
        self.reject()

    def _on_accept(self) -> None:
        self.result_settings = Settings(
            native=self._native.isChecked(),
            pkcs11_lib=self._lib.text().strip(),
            reader=self._reader.text().strip(),
            tsa_url=self._tsa.text().strip(),
            tsa_ca=self._tsa_ca.text().strip(),
            allow_private_network=self._private_network.isChecked(),
            verify_after_sign=self._verify_after.isChecked(),
            check_revocation=self._revocation.isChecked(),
            # Not in this dialog: it lives on Verificar, next to the answer it changes. Carried
            # through so accepting Ajustes never silently turns it back off.
            validate_tsa=self._current.validate_tsa,
            appearance=self._appearance.currentData(),
            stamp_corner=self._stamp_corner.currentData(),
            stamp_margin=self._stamp_margin.value(),
            stamp_image=self._stamp_image.text().strip(),
            stamp_image_mode=self._stamp_mode.currentData(),
            stamp_image_opacity=self._stamp_opacity.value() / 100,
            stamp_title=self._stamp_title.isChecked(),
            stamp_signer=self._stamp_signer.isChecked(),
            stamp_document=self._stamp_document.isChecked(),
            stamp_date=self._stamp_date.isChecked(),
            stamp_issuer=self._stamp_issuer.isChecked(),
            advanced_mode=self._advanced.isChecked(),
            activity_log=self._activity.isChecked(),
            # Carried, not edited. Anything this dialog does not show has to travel through
            # it, or saving Ajustes quietly resets it. test_settings_dialog holds that for
            # every field at once, since the failure is silent and per field.
            window_geometry=self._current.window_geometry,
            window_geometry_min=self._current.window_geometry_min,
        )
        self.accept()


def open_settings(parent: QWidget | None) -> Settings | None:
    """Show the dialog, save on accept, and return what was saved (None when cancelled)."""
    dialog = SettingsDialog(settings_module.load(), parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    settings_module.save(dialog.result_settings)
    return dialog.result_settings
