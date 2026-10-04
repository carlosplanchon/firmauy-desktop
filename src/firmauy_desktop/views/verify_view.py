# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Verificar: drop a signed file and find out whether to trust it.

The layout follows what the person actually asked: the verdict, then one sentence saying what it
means, then who signed, and only then the machinery.

Everything on this screen comes out of a certificate inside a file somebody else sent, which is
why none of it is rendered as markup. Every label here is plain text, so a common name that says
`<img src="file:///etc/passwd">` is a common name that says that, and nothing else happens.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from firmauy_desktop import activity, settings
from firmauy_desktop.backend import (BatchVerifyResult, VerifyResult, verify_batch,
                                     verify_file)
from firmauy_desktop.labels import (TIMESTAMP_MEANING, indication_label,
                                    timestamp_value, unexpected)
from firmauy_desktop.tasks import Deadline, TaskRunner
from firmauy_desktop.ui import components as c
from firmauy_desktop.ui import tokens as ui_tokens
from firmauy_desktop.widgets import Collapsible, DropArea, FileListWidget, ValidatorRow

# What the indication means to somebody who did not ask for a cryptography lesson.
_MEANING = {
    "VALID": "El documento no se modificó desde que se firmó, y el firmante es quien dice ser.",
    # The timestamp joined this list in firmauy 1.12.0, which stopped calling a file VALID over a
    # broken token. Without it the sentence sent somebody looking at their trust anchors for a
    # problem that is in the file, and "falta algo para comprobarlo" is the wrong shape for it:
    # nothing is missing, something does not add up.
    "INDETERMINATE": ("No se puede afirmar que sea válida. Puede que el certificado no llegue "
                      "hasta la raíz nacional, que el sello de tiempo no cierre, o que falte "
                      "algo para comprobarlo."),
    "INVALID": ("No confíes en este archivo. La firma no cierra: el documento pudo cambiar "
                "después de firmarse."),
}

# The plural of _MEANING, for a batch whose files all agree.
_MEANING_BATCH = {
    "VALID": ("Ninguno de los documentos se modificó desde que se firmó, y cada firmante es "
              "quien dice ser."),
    "INDETERMINATE": ("No se puede afirmar que las firmas sean válidas. Puede que algún "
                      "certificado no llegue hasta la raíz nacional, que un sello de tiempo "
                      "no cierre, o que falte algo para comprobarlo."),
    "INVALID": ("No confíes en estos archivos. Las firmas no cierran: los documentos pudieron "
                "cambiar después de firmarse."),
}

# The vocabulary of a batch row: icon, colour token, and what a screen reader says. The spoken
# word matches the word beside the file's name, which is the rule the verdict itself follows.
_ROW_ICONS = {
    "pending": ("dot", "fg.faint", "sin verificar"),
    "valid": ("check", "status.ok", "válido"),
    "indeterminate": ("warning", "status.warn", "indeterminado"),
    "invalid": ("cross", "status.bad", "inválido"),
    "needs_original": ("circle", "fg.muted", "falta el archivo original"),
    "failed": ("cross", "status.bad", "no se pudo verificar"),
}

_ROW_KEY = {"VALID": "valid", "INDETERMINATE": "indeterminate", "INVALID": "invalid"}
_PLURAL = {"VALID": "VÁLIDOS", "INDETERMINATE": "INDETERMINADOS", "INVALID": "INVÁLIDOS"}

# Mirrors Firmar: a stray select-all should be refused, not attempted.
_MAX_BATCH = 200


def _scope_of(indication: str, asked: bool) -> tuple[str, str]:
    """What the verdict above does not cover: a short claim, and the sentence explaining it.

    Depends on the answer, not only on the checkbox, and it is careful about which of three
    things it claims: that nothing was asked, that something was asked and answered, or that
    something was asked and this result says nothing about it.

    Asked plus VÁLIDO licenses the strong claim, because firmauy would not have called it
    valid over a revoked certificate. Anything else only licenses "it was asked for", since
    firmauy can return before it ever gets to the question.

    Two pieces rather than one sentence because of where this sits: directly under a verdict set
    in the largest type the app has. As a single muted caption, the limit of what VÁLIDO means
    was the easiest thing on the screen to discard, and that limit is close to being part of the
    security model. The claim now carries body weight; the explanation stays quiet under it.
    """
    if not asked:
        return ("Revocación: no consultada",
                "Esto no dice si el certificado fue anulado después de emitirse.")
    if indication == "VALID":
        return ("Revocación: consultada",
                "No constaba revocado al momento de la consulta.")
    # "solicitada", not "consultada". Asking is all the app knows it did. Measured: a valid PDF
    # with no signature in it comes back INVALID with one check, "signature present", and no
    # revocation lookup happens at all, because there is no certificate to look up. Saying it
    # was consulted would be describing something that did not happen.
    return ("Revocación: solicitada",
            "Este resultado no confirma el estado del certificado.")


def _batch_scope(asked: bool, all_valid: bool) -> tuple[str, str]:
    """_scope_of, lifted to a batch: the strong claim needs every file to have answered VALID."""
    if not asked:
        return ("Revocación: no consultada",
                "Esto no dice si los certificados fueron anulados después de emitirse.")
    if all_valid:
        return ("Revocación: consultada",
                "Ninguno constaba revocado al momento de la consulta.")
    return ("Revocación: solicitada",
            "Este resultado no confirma el estado de los certificados.")


def _row_state(result: "VerifyResult | None") -> tuple[str, str]:
    """A batch row's status key and the short text beside the file's name.

    The needs_original row keeps its question for the detail zone, where the button is; the
    row itself says only what is missing.
    """
    if result is None:
        return "pending", ""
    if result.error:
        if result.error_kind == "needs_original":
            return "needs_original", "falta el original"
        return "failed", result.error
    return _ROW_KEY[result.indication], indication_label(result.indication)


def _mixed_headline(counts: dict[str, int]) -> tuple[str, str]:
    """The counts sentence for a batch whose files do not agree, and the worst key for its tone.

    A fixed order and no averaging: a batch has no single verdict, and painting one over a mix
    would be lying with colour. The tone still belongs to the worst thing in it.
    """
    total = sum(counts.values())
    parts = []
    for key, singular, plural in (
        ("valid", "válido", "válidos"),
        ("indeterminate", "indeterminado", "indeterminados"),
        ("invalid", "inválido", "inválidos"),
        ("needs_original", "sin su original", "sin su original"),
        ("failed", "no se pudo verificar", "no se pudieron verificar"),
        ("pending", "sin verificar", "sin verificar"),
    ):
        n = counts.get(key, 0)
        if n:
            parts.append(f"{n} {singular if n == 1 else plural}")
    joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " y " + parts[-1]
    if counts.get("invalid"):
        worst = "INVALID"
    elif counts.get("indeterminate"):
        worst = "INDETERMINATE"
    else:
        worst = "WARN"
    return f"De los {total} archivos: {joined}.", worst


class VerifyView(c.Screen):
    def __init__(self) -> None:
        super().__init__(
            "Verificar",
            "Comprobá si un archivo firmado sigue intacto y quién lo firmó. No necesita la "
            "cédula ni, salvo que lo pidas, internet."
        )
        self._path: str | None = None
        self._original: str | None = None
        self._asked_revocation = False      # what the answer on screen was computed with
        # The batch. Exactly one of _path/_paths has content, and _refresh_input reads both.
        self._paths: list[str] = []
        self._results: dict[str, VerifyResult] = {}
        self._batch_total = 0
        self._batch_done = 0
        self._run_anchors: str | None = None    # tsa_ca frozen at start; a row re-verify reuses it
        self._run_private_network = False       # frozen at start the same way, for the same reason
        self._stop = threading.Event()
        self._reverify_path: str | None = None  # one row re-verifying; routes its _on_done
        self._detail_path: str | None = None    # which row the detail zone is about

        self._runner = TaskRunner(self)
        self._runner.finished.connect(self._on_done)
        self._runner.crashed.connect(self._on_crash)
        self._runner.progress.connect(self._on_batch_progress)


        # The answer comes first, above the file that produced it and above the options that
        # shaped it. Fourth thing down, under a large dashed box and two technical checkboxes,
        # opening a signed document reads as filling in a form that also answers you rather
        # than as asking a question and getting an answer.
        # And it comes as one unit. The verdict, what it does not cover and who arbitrates are
        # set tighter than the screen's own rhythm, with a clear break underneath, so the answer
        # reads as one thing and the file row as the next, rather than six blocks at equal
        # distance. Hidden and shown whole: every state that clears the verdict takes the fine
        # print with it, and an empty unit costs the layout nothing.
        self._answer = QWidget()
        answer_column = QVBoxLayout(self._answer)
        answer_column.setContentsMargins(0, 0, 0, ui_tokens.SPACE["md"])
        answer_column.setSpacing(ui_tokens.SPACE["sm"])
        self._verdict = c.Verdict()
        answer_column.addWidget(self._verdict)

        # The batch's headline when its files do not agree: the counts, toned by the worst. The
        # big Verdict cannot carry a counts sentence (verdict type, wrap off), and averaging a
        # mix into one word would put a colour on a claim nobody made.
        self._batch_headline = QWidget()
        headline_row = QHBoxLayout(self._batch_headline)
        headline_row.setContentsMargins(0, 0, 0, 0)
        headline_row.setSpacing(ui_tokens.SPACE["sm"])
        self._batch_icon = c.StatusIcon(size="md")
        headline_row.addWidget(self._batch_icon, alignment=Qt.AlignmentFlag.AlignTop)
        self._batch_text = c.label("", role="subtitle")
        self._batch_text.setMinimumWidth(1)
        headline_row.addWidget(self._batch_text, stretch=1)
        self._batch_headline.hide()
        answer_column.addWidget(self._batch_headline)

        # What the word above it does not cover. With revocation off firmauy runs no revocation
        # check at all, so there is no row for it anywhere: a check that was not run has no
        # result, and its absence is invisible among four green ticks. VÁLIDO then quietly means
        # "intact and correctly signed", which is not the same as "still good".
        #
        # Neutral, not a warning. Off is the default and the honest thing to do is say so, not
        # paint the ordinary case in amber. But not small print either: as one muted caption
        # centred under the largest word in the app, the boundary of what VÁLIDO means is the
        # easiest thing on the screen to skip. The claim carries body weight and sits on the
        # left edge with everything else; the explanation stays quiet.
        self._scope = QWidget()
        scope_column = QVBoxLayout(self._scope)
        scope_column.setContentsMargins(0, 0, 0, 0)
        scope_column.setSpacing(ui_tokens.SPACE["xs"])
        self._scope_head = c.label("", role="body")
        scope_column.addWidget(self._scope_head)
        self._scope_detail = c.Note()
        scope_column.addWidget(self._scope_detail)
        self._scope.hide()
        answer_column.addWidget(self._scope)

        # The arbiter, named at the moment of decision. It sits with the scope lines because it
        # is the same subject: first what this verdict does not cover, then who settles the
        # question when the document matters. The row itself is shared with Firmar's report,
        # so the two screens cannot drift apart on what they claim.
        self._crosscheck = ValidatorRow()
        self._validator_btn = self._crosscheck.button
        self._crosscheck.hide()
        answer_column.addWidget(self._crosscheck)
        self._answer.hide()
        self.body.addWidget(self._answer)

        # Anything that is not a verdict: progress, an error, a timed-out revocation check. In
        # the verdict's own label, "Verificando..." would appear in the same place and the same
        # shape as the answer the person is waiting for.
        self._status = c.Banner()
        self.body.addWidget(self._status)

        # The one place in the app that can sit silent for a long time: with revocation on this
        # waits on an OCSP responder, the text never changes while it does, and a screen that
        # says the same thing for fifteen seconds reads as one that has stopped.
        self._progress = c.Progress()
        self.body.addWidget(self._progress)

        # Only while a verification is in flight, and only useful when revocation is on: a
        # QThread parked in an OCSP fetch cannot be killed, so this stops waiting rather than
        # cancelling. The button says so.
        self._stop_btn = QPushButton("Dejar de esperar")
        self._stop_btn.clicked.connect(self._on_stop)
        self._stop_btn.hide()
        self.body.addWidget(self._stop_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._drop = DropArea("Arrastrá uno o varios archivos firmados acá\n(PDF, XML o .p7s)",
                              multiple=True)
        self._drop.files_selected.connect(self.load_many)
        self.body.addWidget(self._drop)

        # What the drop area shrinks to once there is an answer on screen. The big dashed box is
        # right while it is the only thing to do, and wrong afterwards: it went on spending the
        # most weight on the screen on the step already finished, above the answer the person
        # opened the file to get.
        self._chosen = c.Card()
        chosen_row = QHBoxLayout()
        chosen_row.setContentsMargins(0, 0, 0, 0)
        chosen_row.setSpacing(ui_tokens.SPACE["sm"])
        self._chosen_label = c.label("", tone="muted")
        self._chosen_label.setMinimumWidth(1)
        chosen_row.addWidget(self._chosen_label, stretch=1)
        self._another_btn = QPushButton("Elegir otro...")
        self._another_btn.clicked.connect(self._drop._on_browse)
        chosen_row.addWidget(self._another_btn)
        self._chosen.add_layout(chosen_row)
        self._chosen.hide()
        self.body.addWidget(self._chosen)

        # One row per file of a batch, keyed by path, where Firmar shows each outcome. Selecting
        # a row is how its full answer appears below the list.
        self._files = FileListWidget(icons=_ROW_ICONS)
        self._files.currentRowChanged.connect(self._on_row_selected)
        self._files.hide()
        self.body.addWidget(self._files)

        # Folded away, and after the file rather than before it. These decide how much is
        # checked, which is a question about the verification and not about the document, and
        # they were sitting between the person and the answer in the one place they never
        # belonged: the primary path.
        self._options = Collapsible("Qué comprobar")
        options_body = QWidget()
        options_layout = QVBoxLayout(options_body)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(ui_tokens.SPACE["xs"])

        self._revocation = QCheckBox("Consultar si el certificado fue revocado (usa internet)")
        self._revocation.setChecked(settings.load().check_revocation)
        self._revocation.setToolTip(
            "Sin esto la verificación es totalmente offline.\n"
            "Con esto consulta CRL y OCSP, que puede demorar o no responder."
        )
        self._revocation.toggled.connect(self._on_revocation_toggled)
        options_layout.addWidget(self._revocation)

        # Next to the revocation box because they are the same kind of choice: how much the app
        # is asked to check. Unlike that one this costs nothing and touches no network, and it is
        # still off by default, because it is a trust decision and not a performance one. Nobody
        # has said they accept the bundled roots as timestamping authorities.
        self._validate_tsa = QCheckBox("Comprobar de dónde viene el sello de tiempo")
        self._validate_tsa.setChecked(settings.load().validate_tsa)
        self._validate_tsa.setToolTip(
            "Valida la cadena de la autoridad que selló, contra las raíces públicas que trae la "
            "app. No usa internet.\n"
            "Si tu proveedor no está entre ellas, poné su certificado en Ajustes."
        )
        self._validate_tsa.toggled.connect(self._on_validate_tsa_toggled)
        options_layout.addWidget(self._validate_tsa)

        self._options.add_widget(options_body)
        self.body.addWidget(self._options)

        # Which file the zone below is about. A batch shows many rows and one detail; without a
        # name, the firmante card floats loose from the row it belongs to.
        self._detail_of = c.label("", role="subtitle")
        self._detail_of.hide()
        self.body.addWidget(self._detail_of)

        self._signers = QWidget()
        self._signers_box = QVBoxLayout(self._signers)
        self._signers_box.setContentsMargins(0, 0, 0, 0)
        self._signers_box.setSpacing(ui_tokens.SPACE["md"])
        self.body.addWidget(self._signers)

        self.body.addWidget(self._build_original_row())

        self._details_box = Collapsible("Detalles técnicos")
        self._details = QWidget()
        self._details_layout = QVBoxLayout(self._details)
        self._details_layout.setContentsMargins(0, 0, 0, 0)
        self._details_layout.setSpacing(ui_tokens.SPACE["md"])
        self._details_box.add_widget(self._details)
        self._details_box.hide()
        self.body.addWidget(self._details_box)

        self.body.addStretch()

    def _build_original_row(self) -> QWidget:
        """Shown only when a detached .p7s arrived without the file it signs.

        This is the most common verification failure and the only one the person can fix: the
        signature and the document routinely travel separately by email.
        """
        # A card rather than a bare row: it is the one thing on this screen that asks the person
        # for something, and loose text next to a button reads as a stray sentence.
        self._original_row = c.Card()
        row = QHBoxLayout()
        row.setSpacing(ui_tokens.SPACE["md"])

        self._original_label = c.label("")
        self._original_label.setMinimumWidth(1)
        row.addWidget(self._original_label, stretch=1)

        pick = QPushButton("Elegir el archivo...")
        pick.clicked.connect(self._pick_original)
        row.addWidget(pick)

        self._original_row.add_layout(row)
        self._original_row.hide()
        return self._original_row

    # --- verifying ----------------------------------------------------------

    def load(self, path: str) -> None:
        """Verify ``path``. Public so another screen can send a file here.

        Refused while one is in flight, and refused **before** anything is written down. The
        drop area is disabled during a run, but the Archivo menu and Firmar's "Verificar el
        archivo firmado" both reach here, and they were not. What happened then was the worst
        thing a verifier can do: `_path` became the new file, the runner declined to start, and
        the previous file's verdict arrived onto a screen that now believed it was about this
        one. Nothing on it names the file, so there was nothing to notice.
        """
        if self._runner.busy:
            return
        self._path = path
        self._paths = []
        self._original = None
        self._drop.show_files([path])
        self._refresh_input()
        self._start()

    def load_many(self, paths: list[str]) -> None:
        """Verify several files. One file takes the single road, so that screen never changes.

        Refused while a run is in flight, before anything is written down, for the same reason
        as ``load``. Duplicates collapse: the same file dropped twice is one row, one answer.
        """
        if self._runner.busy:
            return
        unique = list(dict.fromkeys(paths))
        if not unique:
            return
        if len(unique) == 1:
            self.load(unique[0])
            return
        if len(unique) > _MAX_BATCH:
            self._clear_answer()
            self._status.show_message(
                f"Son {len(unique)} archivos y el máximo es {_MAX_BATCH}. "
                "Probá con menos por vez.", tone="warn")
            return
        self._paths = unique
        self._path = None
        self._original = None
        self._drop.show_files(unique)
        self._refresh_input()
        self._start_batch()

    def _refresh_input(self) -> None:
        """Hand the input over to one line once there is a file, so the answer has the screen.

        Driven by ``_path`` rather than called from ``load``, because the screen reaches this
        state by more than one road: the Archivo menu, Firmar's "Verificar el archivo firmado",
        and the storybook driving the handler straight. Hanging presentation off one of those
        entrances is how the drop area kept its full size under an answer in every state but the
        one that was tested.

        Both widgets are kept rather than one being reshaped. The drop area is still the target
        for a second file dragged onto the window, and it goes on receiving one while hidden.
        What changes is which of the two is on screen.
        """
        if self._paths:
            self._chosen_label.setText(
                f"{len(self._paths)} archivos\n{Path(self._paths[0]).parent}")
            self._another_btn.setText("Elegir otros...")
            self._drop.hide()
            self._chosen.show()
            self._files.show()
            return
        self._files.hide()
        if not self._path:
            self._chosen.hide()
            self._drop.show()
            return
        chosen = Path(self._path)
        self._chosen_label.setText(f"{chosen.name}\n{chosen.parent}")
        self._another_btn.setText("Elegir otro...")
        self._drop.hide()
        self._chosen.show()

    def _start(self) -> None:
        if not self._path:
            return
        # Captured, not read again later: the answer that is coming was computed with this value,
        # and the checkbox is only frozen, not gone.
        self._asked_revocation = self._revocation.isChecked()
        current = settings.load()
        anchors = settings.tsa_anchors(current) if self._validate_tsa.isChecked() else None
        if not self._runner.run(verify_file, self._path, original=self._original,
                                check_revocation=self._asked_revocation, tsa_ca=anchors,
                                allow_private_network=current.allow_private_network):
            return                              # already verifying
        self._drop.setEnabled(False)
        self._another_btn.setEnabled(False)
        # Frozen for the duration. Toggling either box mid-run cannot change the answer that is
        # coming, so leaving them live only lets the screen contradict what it is about to say.
        self._revocation.setEnabled(False)
        self._validate_tsa.setEnabled(False)
        self._reverify_path = None
        self._clear_answer()
        self._progress.start()
        self._status.show_message("Verificando...")
        self._stop_btn.setVisible(self._revocation.isChecked())

    def _start_batch(self) -> None:
        if not self._paths:
            return
        self._asked_revocation = self._revocation.isChecked()
        current = settings.load()
        self._run_anchors = (settings.tsa_anchors(current)
                             if self._validate_tsa.isChecked() else None)
        self._run_private_network = current.allow_private_network
        # One Event per run, and the run keeps its own. "Dejar de esperar" sets it and abandons
        # the run, which carries on to the end of the file it is parked in, so it has to find
        # the Event still set when it gets there. A single Event cleared here for the next batch
        # let the abandoned one walk through the rest of its files with nobody waiting for it,
        # revocation lookups included, after the person had switched them off.
        stop = threading.Event()
        self._reverify_path = None
        if not self._runner.run_with_progress(
                verify_batch, list(self._paths),
                should_continue=lambda: not stop.is_set(),
                check_revocation=self._asked_revocation, tsa_ca=self._run_anchors,
                allow_private_network=self._run_private_network):
            return                              # already verifying
        self._stop = stop
        self._drop.setEnabled(False)
        self._another_btn.setEnabled(False)
        self._revocation.setEnabled(False)
        self._validate_tsa.setEnabled(False)
        self._clear_answer()
        self._results = {}
        self._batch_total, self._batch_done = len(self._paths), 0
        self._files.set_paths(self._paths)
        self._progress.start(self._batch_total)
        self._status.show_message("Verificando...")
        self._stop_btn.setVisible(self._revocation.isChecked())

    def _clear_answer(self) -> None:
        """Take the previous answer off the screen, whole. Single and batch share this, so the
        two roads cannot drift on what a fresh run clears."""
        self._verdict.clear()
        self._answer.hide()
        self._scope.hide()
        self._crosscheck.hide()
        self._batch_headline.hide()
        self._detail_of.hide()
        self._detail_path = None
        c.clear_layout(self._signers_box)
        self._original_row.hide()
        self._details_box.hide()

    def _on_stop(self) -> None:
        if self._paths:
            # This run's Event ends the abandoned worker at the next file boundary; abandon frees
            # the screen now. What each row already says stays said.
            self._stop.set()
            self._runner.abandon()
            self._settle()
            self._status.show_message(
                "Se dejó de esperar la consulta de revocación. Los archivos ya verificados "
                "conservan su resultado y el resto quedó sin verificar. Probá de nuevo sin "
                "marcarla.", tone="warn")
            self._show_batch_answer()
            return
        self._runner.abandon()
        self._settle()
        self._verdict.clear()
        self._status.show_message(
            "Se dejó de esperar la consulta de revocación. Probá de nuevo sin marcarla.",
            tone="warn",
        )

    def _on_batch_progress(self, item) -> None:
        """One file of the batch just answered, on its way to the full result."""
        self._results[item.path] = item.result
        self._files.set_status(item.path, *_row_state(item.result))
        self._batch_done += 1
        self._progress.advance(self._batch_done)
        self._status.show_message(
            f"Verificando {self._batch_done} de {self._batch_total}: {Path(item.path).name}")
        if item.path == self._detail_path:
            self._show_row_detail(item.path)    # a pending row somebody was already looking at

    def _on_done(self, result) -> None:
        if isinstance(result, BatchVerifyResult):
            self._on_batch_done(result)
            return
        if self._reverify_path is not None:
            path, self._reverify_path = self._reverify_path, None
            self._on_row_reverified(path, result)
            return
        self._settle()
        if result.error:
            self._verdict.clear()
            if result.error_kind == "needs_original":
                # Not an error banner: it is a question with a button next to it, and the only
                # verification failure the person can actually do something about.
                self._status.clear()
                self._original_label.setText(result.error)
                self._original_row.show()
            else:
                self._status.show_message(result.error, tone="bad")
            return

        self._status.clear()
        self._verdict.set_indication(result.indication, _MEANING.get(result.indication, ""))
        head, detail = _scope_of(result.indication, self._asked_revocation)
        self._scope_head.setText(head)
        self._scope_detail.setText(detail)
        self._scope.show()
        self._crosscheck.show()
        self._answer.show()
        self._show_signers(result)
        self._show_details(result)
        self._details_box.show()

    def _on_batch_done(self, result: BatchVerifyResult) -> None:
        self._settle()
        # The result is the whole truth; the progress reports were only its preview. Applying
        # it again costs nothing and covers any report that never arrived.
        for item in result.items:
            if item.result is not None:
                self._results[item.path] = item.result
                self._files.set_status(item.path, *_row_state(item.result))
        self._status.clear()
        self._show_batch_answer()
        self._on_row_selected(self._files.currentRow())     # a selection made mid-run fills in

    def _show_batch_answer(self) -> None:
        """The aggregate, recomputed from what every row says right now.

        Idempotent on purpose: a stop leaves the batch partial and a row re-verify changes the
        counts, and both just ask again instead of patching the previous sentence.
        """
        counts: dict[str, int] = {}
        for path in self._paths:
            status, _detail = _row_state(self._results.get(path))
            counts[status] = counts.get(status, 0) + 1
        verdicts = sum(counts.get(key, 0) for key in ("valid", "indeterminate", "invalid"))
        shared = [key for key in ("valid", "indeterminate", "invalid")
                  if counts.get(key, 0) == len(self._paths)]
        if shared:
            indication = {"valid": "VALID", "indeterminate": "INDETERMINATE",
                          "invalid": "INVALID"}[shared[0]]
            self._batch_headline.hide()
            self._verdict.set_indication(
                indication, _MEANING_BATCH[indication],
                word=f"Los {len(self._paths)}: {_PLURAL[indication]}")
        else:
            self._verdict.clear()
            sentence, worst = _mixed_headline(counts)
            self._batch_text.setText(sentence)
            c.set_tone(self._batch_text, ui_tokens.STATUS_TONE.get(worst, ""))
            self._batch_icon.set_status(worst)
            self._batch_headline.show()
        if verdicts:
            all_valid = counts.get("valid", 0) == len(self._paths)
            head, detail = _batch_scope(self._asked_revocation, all_valid)
            self._scope_head.setText(head)
            self._scope_detail.setText(detail)
            self._scope.show()
            self._crosscheck.show()
        else:
            self._scope.hide()
            self._crosscheck.hide()
        self._answer.show()

    def _on_row_selected(self, row: int) -> None:
        if row < 0 or not self._paths or row >= len(self._paths):
            self._detail_path = None
            self._detail_of.hide()
            c.clear_layout(self._signers_box)
            self._original_row.hide()
            self._details_box.hide()
            return
        self._show_row_detail(self._paths[row])

    def _show_row_detail(self, path: str) -> None:
        """One row's full answer, under the list: the same rendering a single file gets."""
        self._detail_path = path
        c.clear_layout(self._signers_box)
        self._original_row.hide()
        self._details_box.hide()
        name = Path(path).name
        result = self._results.get(path)
        if result is None:
            self._detail_of.setText(f"{name}: sin verificar")
            self._detail_of.show()
            return
        self._detail_of.setText(f"Detalle de {name}")
        self._detail_of.show()
        if result.error:
            if result.error_kind == "needs_original":
                self._original_label.setText(result.error)
                self._original_row.show()
            else:
                banner = c.Banner()
                banner.show_message(result.error, tone="bad")
                self._signers_box.addWidget(banner)
            return
        self._show_signers(result)
        self._show_details(result)
        self._details_box.show()

    def _show_signers(self, result: VerifyResult) -> None:
        c.clear_layout(self._signers_box)
        many = len(result.signatures) > 1
        for index, sig in enumerate(result.signatures, start=1):
            card = c.Card(f"Firmante {index}" if many else "Firmante")
            rows = c.KeyValueList()
            rows.set_rows(_signer_rows(sig))
            card.add(rows)
            # Only when there is a stamp. On a file without one the row above already says so in
            # four words, and a paragraph of law under every unstamped document would bury the
            # sentence for the files where the date is actually being claimed.
            if sig.timestamp is not None:
                card.add(c.Note(TIMESTAMP_MEANING))
            self._signers_box.addWidget(card)

    def _show_details(self, result: VerifyResult) -> None:
        """Every check, generically. Nothing here switches on a check name: the set differs per
        format, a PDF yields four to six and a XAdES up to ten, and firmauy is free to add more,
        so an unknown one shows up in English rather than disappearing."""
        c.clear_layout(self._details_layout)
        many = len(result.signatures) > 1
        for index, sig in enumerate(result.signatures, start=1):
            # Body rather than caption: it heads the checks below it, and at the caption size
            # (7.5pt against this platform's 9pt base) the accent on VÁLIDO stops being visible
            # at all, which is a poor way to render the word that carries the answer.
            word = indication_label(sig.indication)
            self._details_layout.addWidget(c.label(
                f"Firma {index}: {word}" if many else word, tone="muted"))

            checks = c.CheckList()
            checks.set_checks([
                c.CheckItem("PASS" if check.ok else "FAIL", check.name, check.detail)
                for check in sig.checks
            ])
            self._details_layout.addWidget(checks)

            if sig.signer.certificate_serial:
                serial = c.KeyValueList()
                serial.set_rows([c.Row("Serie del certificado", sig.signer.certificate_serial,
                                       role="mono")])
                self._details_layout.addWidget(serial)

    def _on_crash(self) -> None:
        self._reverify_path = None
        self._settle()
        self._verdict.clear()
        self._status.show_message(
            unexpected("La verificación", recorded=activity.is_on()),
            tone="bad",
        )

    def _settle(self) -> None:
        self._refresh_input()
        self._progress.stop()
        self._drop.setEnabled(True)
        self._another_btn.setEnabled(True)
        self._revocation.setEnabled(True)
        self._validate_tsa.setEnabled(True)
        self._stop_btn.hide()

    # --- the missing original -----------------------------------------------

    def _pick_original(self) -> None:
        if self._paths:
            self._reverify_row()
            return
        path, _ = QFileDialog.getOpenFileName(self, "Elegir el archivo que se firmó")
        if not path:
            return
        self._original = path
        self._original_row.hide()
        self._start()

    def _reverify_row(self) -> None:
        """The batch's answer to a detached .p7s: pick its original and re-verify that row
        alone, with the options the batch ran with, so one answer cannot mix two
        configurations."""
        if self._runner.busy or self._detail_path is None:
            return
        path = self._detail_path
        chosen, _ = QFileDialog.getOpenFileName(self, "Elegir el archivo que se firmó")
        if not chosen:
            return
        self._reverify_path = path
        if not self._runner.run(verify_file, path, original=chosen,
                                check_revocation=self._asked_revocation,
                                tsa_ca=self._run_anchors,
                                allow_private_network=self._run_private_network):
            self._reverify_path = None
            return
        self._drop.setEnabled(False)
        self._another_btn.setEnabled(False)
        self._revocation.setEnabled(False)
        self._validate_tsa.setEnabled(False)
        self._original_row.hide()
        self._progress.start()
        self._status.show_message(f"Verificando {Path(path).name}...")

    def _on_row_reverified(self, path: str, result: VerifyResult) -> None:
        self._settle()
        self._status.clear()
        self._results[path] = result
        self._files.set_status(path, *_row_state(result))
        self._show_batch_answer()
        if self._detail_path == path:
            self._show_row_detail(path)

    def _on_revocation_toggled(self, on: bool) -> None:
        """Persist it, so Ajustes and this checkbox never disagree."""
        current = settings.load()
        current.check_revocation = on
        settings.save(current)

    def _on_validate_tsa_toggled(self, on: bool) -> None:
        current = settings.load()
        current.validate_tsa = on
        settings.save(current)

    def shutdown(self, budget: "int | Deadline" = 5000) -> list:
        """Wait for work in flight, so the window can close without destroying a live thread.

        The stop comes first, so a batch ends at the file it is on instead of working through
        the rest of the queue while the window waits.
        """
        self._stop.set()
        return self._runner.shutdown(budget)


def _signer_rows(sig) -> list[c.Row]:
    rows = [c.Row("Nombre", sig.signer.common_name)]
    if sig.signer.serial_number:
        # The signer's cédula, as the certificate spells it (often prefixed, e.g. DNI…).
        rows.append(c.Row("Cédula", sig.signer.serial_number))
    if sig.signer.organization:
        rows.append(c.Row("Organización", sig.signer.organization))
    if sig.issuer.common_name:
        rows.append(c.Row("Emitido por", sig.issuer.common_name))
    rows.append(c.Row(
        "Cadena de confianza",
        "llega a la raíz nacional" if sig.trusted else "no llega a la raíz nacional",
        mark=sig.trusted,
    ))

    # Always a row, even with no stamp. "When was this signed?" is one of the two questions
    # somebody opens this screen with, and an absent row is not an answer: nobody notices a row
    # that is not there. The verdict above says whether the signature holds and is silent about
    # the date, so this is the only place the distinction gets made.
    ts = sig.timestamp
    rows.append(c.Row("Sello de tiempo", timestamp_value(ts), mark=_timestamp_mark(ts)))
    if ts is not None and ts.tsa:
        # Worth naming, because who issued it is exactly what decides whether Ley 18.600 is
        # satisfied. The note under this list explains why that matters.
        rows.append(c.Row("Sellado por", ts.tsa))
    return rows


def _timestamp_mark(ts) -> bool | None:
    """The tick, the cross, or nothing.

    Nothing when there is no stamp: an absent stamp is not a failure, it only means the date was
    never part of what was proved, and a red cross would read as a defect in the document.
    """
    if ts is None:
        return None
    return ts.sound and ts.trusted is not False
