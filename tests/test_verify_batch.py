# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for batch verification: the backend loop, and the Verificar screen driving it.

One file through load_many must behave exactly like the single screen, which the whole of
test_verify_view.py holds untouched; everything here is about several.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt

from conftest import widget_text
from firmauy_desktop import activity, backend
from firmauy_desktop.views import verify_view
from firmauy_desktop.widgets import FileListWidget


# --- the backend loop --------------------------------------------------------

class _Report:
    """The least a firmauy VerifyReport needs to look like: indication plus signatures."""

    def __init__(self, indication: str = "VALID") -> None:
        self.indication = indication
        self.signatures = []


def _fake_api(answers):
    """A per-path _api_verify: ``answers[path]`` is an indication, or an exception to raise."""
    def fake(path, *, original=None, check_revocation=False, tsa_ca=None,
             allow_private_network=False):
        answer = answers[str(path)]
        if isinstance(answer, Exception):
            raise answer
        return _Report(answer)
    return fake


def test_verify_batch_answers_each_file_in_the_order_given(monkeypatch):
    paths = ["/tmp/a.pdf", "/tmp/b.xml", "/tmp/c.pdf"]
    monkeypatch.setattr(backend, "_api_verify", _fake_api(
        {paths[0]: "VALID", paths[1]: "INVALID", paths[2]: "VALID"}))
    seen = []

    result = backend.verify_batch(paths, progress=seen.append)

    assert result.ok is True
    assert [item.path for item in result.items] == paths
    assert [item.result.indication for item in result.items] == ["VALID", "INVALID", "VALID"]
    assert [item.path for item in seen] == paths        # told once per file, as it landed


def test_a_file_that_cannot_be_verified_is_a_row_not_a_stop(monkeypatch):
    paths = ["/tmp/a.pdf", "/tmp/rota.bin", "/tmp/c.pdf"]
    monkeypatch.setattr(backend, "_api_verify", _fake_api({
        paths[0]: "VALID",
        paths[1]: ValueError("could not detect the signature type"),
        paths[2]: "VALID"}))

    result = backend.verify_batch(paths)

    assert result.ok is True                            # the batch ran to the end
    assert result.items[1].result.error
    assert result.items[2].result.indication == "VALID"     # the one after still answered


def test_a_missing_original_does_not_block_the_batch(monkeypatch):
    from firmauy.errors import DetachedOriginalRequiredError

    paths = ["/tmp/a.pdf", "/tmp/suelto.p7s"]
    monkeypatch.setattr(backend, "_api_verify", _fake_api({
        paths[0]: "VALID",
        paths[1]: DetachedOriginalRequiredError("detached", expected=Path("/tmp/suelto"))}))

    result = backend.verify_batch(paths)

    assert result.ok is True
    assert result.items[1].result.error_kind == "needs_original"


def test_should_continue_is_asked_between_files_and_stops_there(monkeypatch):
    paths = [f"/tmp/f{i}.pdf" for i in range(4)]
    monkeypatch.setattr(backend, "_api_verify", _fake_api({p: "VALID" for p in paths}))
    answers = iter([True, True, False])

    result = backend.verify_batch(paths, should_continue=lambda: next(answers))

    assert result.ok is False
    assert result.error_kind == "cancelled"
    assert result.error == ""                           # a stop is a choice, not a failure
    assert [item.result is not None for item in result.items] == [True, True, False, False]


def test_the_batch_options_reach_every_call(monkeypatch):
    calls = []

    def fake(path, *, original=None, check_revocation=False, tsa_ca=None,
             allow_private_network=False):
        calls.append((str(path), check_revocation, tsa_ca, allow_private_network))
        return _Report("VALID")

    monkeypatch.setattr(backend, "_api_verify", fake)
    backend.verify_batch(["/tmp/a.pdf", "/tmp/b.pdf"], check_revocation=True,
                         tsa_ca="/tmp/ca.pem", allow_private_network=True)

    assert calls == [("/tmp/a.pdf", True, "/tmp/ca.pem", True),
                     ("/tmp/b.pdf", True, "/tmp/ca.pem", True)]


def test_a_batch_writes_two_lines_in_the_record_not_two_per_file(monkeypatch):
    paths = [f"/tmp/f{i}.pdf" for i in range(3)]
    monkeypatch.setattr(backend, "_api_verify", _fake_api({p: "VALID" for p in paths}))
    activity.configure(True)
    activity.clear()

    backend.verify_batch(paths)

    written = activity.log_path().read_text(encoding="utf-8")
    assert "lote a verificar" in written and "total=3" in written
    assert "lote verificado" in written and "n=3" in written
    assert "verificación lista" not in written
    activity.configure(False)


def test_a_single_verification_still_records_itself(monkeypatch):
    """Guards the _verify_one split: quieting the batch must not quiet the single road."""
    monkeypatch.setattr(backend, "_api_verify", _fake_api({"/tmp/a.pdf": "VALID"}))
    activity.configure(True)
    activity.clear()

    backend.verify_file("/tmp/a.pdf")

    written = activity.log_path().read_text(encoding="utf-8")
    assert "verificación lista" in written
    activity.configure(False)


# --- the screen --------------------------------------------------------------

def _verdict(indication: str = "VALID", signer: str = "PEREZ PEREZ JUAN") -> backend.VerifyResult:
    return backend.VerifyResult(indication, [backend.Signature(
        indication=indication, trusted=indication == "VALID",
        signer=backend.Party(signer, "DNI12345672", "", "UY", "0A1B"),
        issuer=backend.Party("Autoridad Certificadora del Ministerio del Interior"),
        checks=[backend.Check("signature cryptographically valid", indication != "INVALID")])])


def _needs_original(name: str = "convenio.pdf") -> backend.VerifyResult:
    return backend.VerifyResult(
        "", error=f"Este .p7s está separado del archivo que firmó. Se buscó {name} al lado "
                  "y no está. ¿Cuál es?", error_kind="needs_original")


def _batch_fake(mapping):
    """A verify_batch that reports each file as it lands, like the real one."""
    def fake(paths, *, progress=None, should_continue=None, **kw):
        items = []
        for p in paths:
            item = backend.VerifiedItem(p, mapping[p])
            items.append(item)
            if progress is not None:
                progress(item)
        return backend.BatchVerifyResult(True, items)
    return fake


def _run_batch(qtbot, view, paths):
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view.load_many(paths)


def test_dropping_several_files_verifies_them_all_with_a_verdict_per_row(
        make_view, qtbot, fake_backend):
    paths = ["/tmp/a.pdf", "/tmp/b.xml"]
    fake_backend.patch(verify_view, "verify_batch", side_effect=_batch_fake(
        {paths[0]: _verdict("VALID"), paths[1]: _verdict("INVALID")}))

    view = make_view(verify_view.VerifyView)
    _run_batch(qtbot, view, paths)

    assert view._files.isHidden() is False
    rows = [view._files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(2)]
    assert rows == ["valid", "invalid"]
    name, args, _kwargs = fake_backend.calls[0]
    assert name == "verify_batch" and list(args[0]) == paths    # one call, every file


def test_a_batch_of_equals_gets_one_sentence(make_view, qtbot, fake_backend):
    paths = [f"/tmp/f{i}.pdf" for i in range(3)]
    fake_backend.patch(verify_view, "verify_batch", side_effect=_batch_fake(
        {p: _verdict("VALID") for p in paths}))

    view = make_view(verify_view.VerifyView)
    _run_batch(qtbot, view, paths)

    assert "Los 3: VÁLIDOS" in widget_text(view._answer)
    assert "Ninguno de los documentos se modificó" in widget_text(view._answer)
    assert view._batch_headline.isHidden() is True


def test_a_mixed_batch_counts_by_verdict_and_takes_the_worst_tone(make_view, qtbot,
                                                                  fake_backend):
    paths = ["/tmp/a.pdf", "/tmp/b.pdf", "/tmp/c.p7s"]
    fake_backend.patch(verify_view, "verify_batch", side_effect=_batch_fake(
        {paths[0]: _verdict("VALID"), paths[1]: _verdict("INVALID"),
         paths[2]: _needs_original()}))

    view = make_view(verify_view.VerifyView)
    _run_batch(qtbot, view, paths)

    assert view._verdict.isHidden() is True             # no single word over a mix
    assert view._batch_headline.isHidden() is False
    text = widget_text(view._batch_headline)
    assert "De los 3 archivos" in text
    assert "1 válido, 1 inválido y 1 sin su original" in text
    assert view._batch_text.property("tone") == "bad"


def test_selecting_a_row_shows_that_files_answer_below_the_list(make_view, qtbot,
                                                                fake_backend):
    paths = ["/tmp/a.pdf", "/tmp/b.pdf"]
    fake_backend.patch(verify_view, "verify_batch", side_effect=_batch_fake(
        {paths[0]: _verdict("VALID", signer="ANA PEREZ"),
         paths[1]: _verdict("VALID", signer="JUAN GOMEZ")}))

    view = make_view(verify_view.VerifyView)
    _run_batch(qtbot, view, paths)
    view._files.setCurrentRow(1)

    assert "Detalle de b.pdf" in widget_text(view._detail_of)
    assert "JUAN GOMEZ" in widget_text(view._signers)
    assert "ANA PEREZ" not in widget_text(view._signers)
    assert view._files.isHidden() is False              # the list stays above the detail


def test_a_row_missing_its_original_re_verifies_only_that_row(make_view, qtbot, fake_backend,
                                                              monkeypatch):
    paths = ["/tmp/a.pdf", "/tmp/suelto.p7s"]
    fake_backend.patch(verify_view, "verify_batch", side_effect=_batch_fake(
        {paths[0]: _verdict("VALID"), paths[1]: _needs_original("suelto")}))

    view = make_view(verify_view.VerifyView)
    _run_batch(qtbot, view, paths)
    view._files.setCurrentRow(1)
    assert view._original_row.isHidden() is False

    fake_backend.patch(verify_view, "verify_file", _verdict("VALID"))
    monkeypatch.setattr(verify_view.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("/tmp/suelto", "")))
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._pick_original()

    assert fake_backend.kwargs_for("verify_file")["original"] == str(Path("/tmp/suelto"))
    assert view._files.item(1).data(Qt.ItemDataRole.UserRole) == "valid"
    assert view._files.item(0).data(Qt.ItemDataRole.UserRole) == "valid"    # untouched
    assert "Los 2: VÁLIDOS" in widget_text(view._answer)                    # recounted


def test_a_row_re_verify_reaches_the_network_the_batch_reached(make_view, qtbot, fake_backend,
                                                               monkeypatch):
    """One answer cannot mix two configurations, so a row re-verified after Ajustes changed uses
    what the batch ran with, like its timestamp anchors."""
    from firmauy_desktop import settings

    paths = ["/tmp/a.pdf", "/tmp/suelto.p7s"]
    fake_backend.patch(verify_view, "verify_batch", side_effect=_batch_fake(
        {paths[0]: _verdict("VALID"), paths[1]: _needs_original("suelto")}))
    settings.save(settings.Settings(allow_private_network=True))

    view = make_view(verify_view.VerifyView)
    _run_batch(qtbot, view, paths)
    assert fake_backend.kwargs_for("verify_batch")["allow_private_network"] is True

    settings.save(settings.Settings(allow_private_network=False))       # changed mid-way
    view._files.setCurrentRow(1)
    fake_backend.patch(verify_view, "verify_file", _verdict("VALID"))
    monkeypatch.setattr(verify_view.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("/tmp/suelto", "")))
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._pick_original()

    assert fake_backend.kwargs_for("verify_file")["allow_private_network"] is True


def test_one_file_through_load_many_keeps_the_single_screen(make_view, qtbot, fake_backend):
    fake_backend.patch(verify_view, "verify_file", _verdict("VALID"))
    fake_backend.patch(verify_view, "verify_batch", None)

    view = make_view(verify_view.VerifyView)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view.load_many(["/tmp/solo.pdf"])

    assert [name for name, *_rest in fake_backend.calls] == ["verify_file"]
    assert view._files.isHidden() is True
    assert "VÁLIDO" in widget_text(view._verdict)


def test_too_many_files_is_refused_rather_than_attempted(make_view, qtbot, fake_backend):
    view = make_view(verify_view.VerifyView)

    view.load_many([f"/tmp/f{i}.pdf" for i in range(201)])

    assert fake_backend.calls == []
    assert "máximo es 200" in widget_text(view._status)
    assert view._paths == []                            # refused before anything was written


def test_stopping_a_batch_keeps_the_verdicts_already_delivered(make_view, qtbot, fake_backend):
    paths = ["/tmp/a.pdf", "/tmp/b.pdf", "/tmp/c.pdf"]
    gate = threading.Event()

    def slow(batch_paths, *, progress=None, should_continue=None, **kw):
        items = [backend.VerifiedItem(p) for p in batch_paths]
        items[0].result = _verdict("VALID")
        if progress is not None:
            progress(items[0])
        gate.wait(5)                                    # the OCSP that never answers
        return backend.BatchVerifyResult(True, items)

    fake_backend.patch(verify_view, "verify_batch", side_effect=slow)
    view = make_view(verify_view.VerifyView)
    view.load_many(paths)
    qtbot.waitUntil(lambda: view._batch_done == 1, timeout=5000)

    view._on_stop()
    gate.set()

    assert view._runner.busy is False
    assert view._stop.is_set()
    assert view._files.item(0).data(Qt.ItemDataRole.UserRole) == "valid"
    assert view._files.item(1).data(Qt.ItemDataRole.UserRole) == "pending"
    assert "quedó sin verificar" in widget_text(view._status)
    assert "De los 3 archivos" in widget_text(view._batch_headline)


def test_a_stopped_batch_stays_stopped_when_the_next_one_starts(make_view, qtbot, fake_backend):
    """Stopping abandons a batch parked in a lookup that cannot be interrupted, and the batch
    carries on to the end of that file. It shared one Event with the next batch, which cleared it
    on the way in, so the abandoned one found nothing telling it to stop and went on through the
    rest of its files with its own options: revocation lookups the person had just stopped waiting
    for, and switched off, as the warning suggests."""
    parked, gate, abandoned_ended = threading.Event(), threading.Event(), threading.Event()
    verified, lock = [], threading.Lock()

    def batch(paths, *, progress=None, should_continue=None, check_revocation=False, **kw):
        # The real loop's shape: ask before each file, then verify it.
        items = [backend.VerifiedItem(p) for p in paths]
        try:
            for item in items:
                if should_continue is not None and not should_continue():
                    return backend.BatchVerifyResult(False, items, "", "cancelled")
                with lock:
                    verified.append((item.path, check_revocation))
                if item.path == "/tmp/a1.pdf":
                    parked.set()
                    gate.wait(5)                        # the OCSP responder that never answers
                item.result = _verdict("VALID")
                if progress is not None:
                    progress(item)
            return backend.BatchVerifyResult(True, items)
        finally:
            if paths[0] == "/tmp/a1.pdf":
                abandoned_ended.set()

    fake_backend.patch(verify_view, "verify_batch", side_effect=batch)
    view = make_view(verify_view.VerifyView)
    view._revocation.setChecked(True)
    view.load_many(["/tmp/a1.pdf", "/tmp/a2.pdf", "/tmp/a3.pdf"])
    qtbot.waitUntil(parked.is_set, timeout=5000)

    view._on_stop()
    view._revocation.setChecked(False)
    _run_batch(qtbot, view, ["/tmp/b1.pdf", "/tmp/b2.pdf"])
    gate.set()                                          # the lookup finally answers
    # Waited for on its own, not through shutdown(): that sets the stop on the way in and would
    # end the abandoned batch whether or not anything else did.
    qtbot.waitUntil(abandoned_ended.is_set, timeout=5000)

    with lock:
        assert verified == [("/tmp/a1.pdf", True), ("/tmp/b1.pdf", False),
                            ("/tmp/b2.pdf", False)]


def test_the_crosscheck_row_appears_once_with_the_batch_result(make_view, qtbot, fake_backend):
    paths = ["/tmp/a.pdf", "/tmp/b.pdf"]
    fake_backend.patch(verify_view, "verify_batch", side_effect=_batch_fake(
        {p: _verdict("VALID") for p in paths}))

    view = make_view(verify_view.VerifyView)
    assert view._crosscheck.isHidden() is True
    _run_batch(qtbot, view, paths)

    assert view._crosscheck.isHidden() is False
    assert "Revocación: no consultada" in widget_text(view._answer)


def test_a_second_drop_cannot_be_taken_while_a_batch_runs(make_view, qtbot, fake_backend):
    gate = threading.Event()

    def slow(paths, **kw):
        gate.wait(5)
        return backend.BatchVerifyResult(True, [backend.VerifiedItem(p) for p in paths])

    fake_backend.patch(verify_view, "verify_batch", side_effect=slow)
    view = make_view(verify_view.VerifyView)
    first = ["/tmp/a.pdf", "/tmp/b.pdf"]
    view.load_many(first)

    view.load_many(["/tmp/x.pdf", "/tmp/y.pdf"])        # refused, before anything is written

    assert view._paths == first
    gate.set()


def test_the_batch_progress_counts_files(make_view, qtbot, fake_backend):
    paths = [f"/tmp/f{i}.pdf" for i in range(3)]
    fake_backend.patch(verify_view, "verify_batch", side_effect=_batch_fake(
        {p: _verdict("VALID") for p in paths}))

    view = make_view(verify_view.VerifyView)
    _run_batch(qtbot, view, paths)

    assert view._batch_total == 3
    assert view._batch_done == 3
    assert view._progress.maximum() == 3


def test_the_scope_line_describes_the_whole_run(make_view, qtbot, fake_backend):
    paths = ["/tmp/a.pdf", "/tmp/b.pdf"]
    fake_backend.patch(verify_view, "verify_batch", side_effect=_batch_fake(
        {p: _verdict("VALID") for p in paths}))

    view = make_view(verify_view.VerifyView)
    view._revocation.setChecked(True)
    _run_batch(qtbot, view, paths)

    assert "Revocación: consultada" in widget_text(view._answer)
    assert "Ninguno constaba revocado" in widget_text(view._answer)


def test_a_selection_survives_the_list_being_rebuilt(make_view, qtbot, fake_backend):
    paths = ["/tmp/a.pdf", "/tmp/b.pdf"]
    fake_backend.patch(verify_view, "verify_batch", side_effect=_batch_fake(
        {p: _verdict("VALID") for p in paths}))

    view = make_view(verify_view.VerifyView)
    _run_batch(qtbot, view, paths)
    view._files.setCurrentRow(1)
    assert view._detail_path == paths[1]

    view._files.set_paths(paths)                        # what a new run does; fires row -1

    assert view._detail_path is None
    assert view._detail_of.isHidden() is True


# --- the widget --------------------------------------------------------------

def test_the_file_list_takes_a_vocabulary_of_its_own(qapp):
    """Verify speaks in verdicts where Firmar speaks in outcomes, on the same widget."""
    files = FileListWidget(icons={"pending": ("dot", "fg.faint", "sin verificar"),
                                  "valid": ("check", "status.ok", "válido")})
    files.set_paths(["/tmp/a.pdf"])
    files.set_status("/tmp/a.pdf", "valid")

    assert files.item(0).data(Qt.ItemDataRole.UserRole) == "valid"
    assert "válido" in files.item(0).data(Qt.ItemDataRole.AccessibleTextRole)

    default = FileListWidget()
    default.set_paths(["/tmp/b.pdf"])
    default.set_status("/tmp/b.pdf", "signed")
    assert "firmado" in default.item(0).data(Qt.ItemDataRole.AccessibleTextRole)
