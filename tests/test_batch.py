# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for signing several files at once.

The point of a batch is one card session and therefore one PIN. The point of the pre-flight is
that the likeliest way a batch breaks becomes a question asked before that PIN.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from firmauy.api import (BatchSignError, OutputAccessControlError, OutputCommittedError,
                         OutputExistsError, PinLastTryError, PostSignVerificationError, SignReport,
                         TimestampDestinationRefusedError)

from PySide6.QtCore import Qt

from conftest import widget_text
from firmauy_desktop import backend
from firmauy_desktop.views import sign_view


def _status(view, row: int) -> str:
    """What the row says it is. Read from the data role rather than sniffed out of the text:
    the status used to be an emoji inside the label, which could not be coloured and read out
    to a screen reader as "white heavy check mark"."""
    return view._files.item(row).data(Qt.ItemDataRole.UserRole)


def _files(tmp_path, names) -> list[str]:
    paths = []
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"contenido")
        paths.append(str(path))
    return paths


# --- the pre-flight ---------------------------------------------------------

def test_preflight_sorts_the_batch(tmp_path):
    ready = _files(tmp_path, ["a.bin", "b.bin"])
    (tmp_path / "b.bin.p7s").write_bytes(b"ya firmado")
    missing = str(tmp_path / "no-existe.bin")
    folder = tmp_path / "carpeta"
    folder.mkdir()

    report = backend.preflight_batch([*ready, missing, str(folder)])

    assert report.ready == [ready[0]]
    assert report.conflicts == [(ready[1], str(tmp_path / "b.bin.p7s"))]
    assert [why for _p, why in report.problems] == ["no existe", "es una carpeta"]
    assert report.total == 4


def test_preflight_catches_two_inputs_landing_on_one_output(tmp_path):
    """Without this the second silently overwrites the first, mid-batch, with --overwrite on."""
    one = tmp_path / "sub1"
    two = tmp_path / "sub2"
    one.mkdir()
    two.mkdir()
    (one / "doc.bin").write_bytes(b"a")
    (two / "doc.bin").write_bytes(b"b")

    report = backend.preflight_batch(
        [str(one / "doc.bin"), str(two / "doc.bin")], output_dir=str(tmp_path / "out"))

    assert report.ready == [str(one / "doc.bin")]
    assert "chocaría con doc.bin" in report.problems[0][1]


def test_preflight_never_raises(tmp_path):
    """It runs before anything else, so a path it cannot make sense of is a row, not a crash."""
    report = backend.preflight_batch(["", "\x00raro", str(tmp_path)])
    assert report.ready == []
    assert len(report.problems) == 3


# --- the batch itself -------------------------------------------------------

def test_sign_batch_reports_each_file_as_it_lands(monkeypatch, tmp_path):
    paths = _files(tmp_path, ["a.bin", "b.bin"])
    seen = []

    def fake(items, *, pin_provider, progress, **kw):
        for index, src in enumerate(items):
            out = Path(str(src) + ".p7s")
            out.write_bytes(b"firma")
            progress(index, Path(src), out)
        return [SignReport(output_path=Path(p + ".p7s"), signer="X", issuer="Y") for p in items]

    monkeypatch.setattr(backend, "_api_sign_files", fake)

    result = backend.sign_batch(paths, pin_provider=lambda: "1234", progress=seen.append)

    assert result.ok is True
    assert result.signed == 2
    assert [item.path for item in seen] == paths
    assert all(Path(item.output_path).exists() for item in seen)   # told only once it is written


def test_sign_batch_hands_back_what_was_already_signed(monkeypatch, tmp_path):
    """Fail-fast, but not silently: those signatures are real and the person needs to know."""
    paths = _files(tmp_path, ["a.bin", "b.bin", "c.bin"])

    def fake(items, *, pin_provider, progress, **kw):
        out = Path(items[0] + ".p7s")
        out.write_bytes(b"firma")
        progress(0, Path(items[0]), out)
        raise BatchSignError(
            "stopped", completed=[SignReport(output_path=out, signer="X", issuer="Y")],
            failed_index=1, failed_path=Path(items[1]),
        ) from OutputExistsError("exists", path=Path(items[1] + ".p7s"))

    monkeypatch.setattr(backend, "_api_sign_files", fake)

    result = backend.sign_batch(paths, pin_provider=lambda: "1234")

    assert result.ok is False
    assert result.signed == 1
    assert result.items[0].status == "signed"
    assert result.items[1].status == "failed"
    assert "Ya existe" in result.items[1].detail
    assert result.items[2].status == "pending"          # never attempted
    assert result.error_kind == "output_exists"
    assert result.conflict_path.endswith("b.bin.p7s")


def test_a_tsa_the_batch_cannot_reach_stops_it_at_that_file_and_says_why(monkeypatch, tmp_path):
    """The stamp is asked for per file, so the failure arrives as the cause of a BatchSignError at
    the file it stopped on, after the ones before it were written."""
    paths = _files(tmp_path, ["a.bin", "b.bin", "c.bin"])

    def fake(items, *, pin_provider, progress, **kw):
        out = Path(items[0] + ".p7s")
        out.write_bytes(b"firma")
        progress(0, Path(items[0]), out)
        raise BatchSignError(
            "stopped", completed=[SignReport(output_path=out, signer="X", issuer="Y")],
            failed_index=1, failed_path=Path(items[1]),
        ) from TimestampDestinationRefusedError("Refusing to connect to 10.0.0.5.",
                                                host="10.0.0.5")

    monkeypatch.setattr(backend, "_api_sign_files", fake)

    result = backend.sign_batch(paths, pin_provider=lambda: "1234")

    assert result.items[0].status == "signed"
    assert result.items[1].status == "failed"
    assert "Permitir servidores de la red local" in result.items[1].detail
    assert result.error_kind == "tsa_destination_refused"


def test_a_progress_callback_that_raises_does_not_unsign_the_file(monkeypatch, tmp_path):
    """firmauy writes the output, counts it in `completed`, and only then announces it, so a
    callback that raises leaves `failed_index` pointing at a file that is signed and on disk.
    BatchSignError says so in as many words: "the file at failed_index can itself appear in
    completed", for OutputCommittedError and for this.

    Reported as failed, the one sensible thing a person can do is sign it again, over an output
    that already exists and is fine. `callback_error` is how firmauy distinguishes the two, and
    reading it is the whole reason it exists. Index arithmetic against `completed` is not the
    alternative: the same docstring warns that len(completed) is not always failed_index.
    """
    paths = _files(tmp_path, ["a.bin", "b.bin"])

    def fake(items, *, pin_provider, progress, **kw):
        out = Path(items[0] + ".p7s")
        out.write_bytes(b"firma")
        try:
            progress(0, Path(items[0]), out)
        except Exception as exc:      # firmauy's _announce, which catches and hands it back
            raise BatchSignError(
                "stopped after a.bin: the progress callback raised. The signature was written.",
                completed=[SignReport(output_path=out, signer="X", issuer="Y")],
                failed_index=0, failed_path=Path(items[0]), callback_error=exc,
            ) from exc
        raise AssertionError("the callback did not raise, so this test would prove nothing")

    monkeypatch.setattr(backend, "_api_sign_files", fake)

    def boom(item):
        # What this looks like in practice: the view is torn down mid-batch and emitting a signal
        # from the worker touches a deleted C++ object.
        raise RuntimeError("wrapped C/C++ object of type SignView has been deleted")

    result = backend.sign_batch(paths, pin_provider=lambda: "1234", progress=boom)

    assert result.ok is False
    assert result.items[0].status == "signed", "a file that is signed and on disk read as failed"
    assert result.items[0].output_path.endswith("a.bin.p7s")
    assert result.signed == 1
    assert result.items[1].status == "pending"          # never attempted

    # And the batch says what happened instead of handing over the callback's own words.
    assert result.error_kind == "callback_failed"
    # "guardado", not "bien": sign_batch defaults verify to False, so what is known is that the
    # file was written. Claiming more would be the app inventing a check it never ran.
    assert "Se firmó 1 archivo y quedó guardado" in result.error
    assert "C/C++" not in result.error


def test_a_callback_that_raises_over_a_committed_output_still_says_to_repair_it(monkeypatch,
                                                                                tmp_path):
    """Both can happen at once: firmauy announces an OutputCommittedError too, so its progress
    call can raise on the very file whose permissions need fixing. Then `callback_error` is set
    and `__cause__` is still the OutputCommittedError, which is the one that has something for
    the person to do. Order the two checks the other way and the repair notice disappears.
    """
    paths = _files(tmp_path, ["a.bin"])

    def fake(items, *, pin_provider, progress, **kw):
        out = Path(items[0] + ".p7s")
        out.write_bytes(b"firma")
        committed = OutputCommittedError("mode", path=out, final_mode=0o600, errno=1)
        try:
            progress(0, Path(items[0]), out)
        except Exception as exc:
            raise BatchSignError(
                "stopped", completed=[SignReport(output_path=out, signer="X", issuer="Y")],
                failed_index=0, failed_path=Path(items[0]), callback_error=exc,
            ) from committed
        raise AssertionError("the callback did not raise, so this test would prove nothing")

    monkeypatch.setattr(backend, "_api_sign_files", fake)

    result = backend.sign_batch(paths, pin_provider=lambda: "1234",
                                progress=lambda item: (_ for _ in ()).throw(RuntimeError("gone")))

    assert result.items[0].status == "warned"
    assert "permisos" in result.items[0].detail
    assert result.error_kind == "output_committed"      # the actionable one wins


def test_sign_batch_reports_a_cancelled_pin(monkeypatch, tmp_path):
    def fake(items, *, pin_provider, progress, **kw):
        raise backend.PinCancelled

    monkeypatch.setattr(backend, "_api_sign_files", fake)

    result = backend.sign_batch(_files(tmp_path, ["a.bin"]), pin_provider=lambda: "")
    assert result.error_kind == "cancelled"
    assert result.signed == 0


def test_a_batch_turned_away_before_the_prompt_signs_nothing_and_says_why(monkeypatch, tmp_path):
    """The PIN is asked once, while the session opens, so a card on its last try stops the batch
    before its first file and outside BatchSignError."""
    def fake(items, *, pin_provider, progress, **kw):
        raise PinLastTryError("Only 1 PIN try left: aborting for safety.")

    monkeypatch.setattr(backend, "_api_sign_files", fake)

    result = backend.sign_batch(_files(tmp_path, ["a.pdf", "b.pdf"]), pin_provider=lambda: "1234")

    assert result.ok is False
    assert result.error_kind == "pin_last_try"
    assert result.signed == 0
    assert "desbloquearla" in result.error


# --- the screen -------------------------------------------------------------

def _patch_batch(fake_backend, result):
    return fake_backend.patch(sign_view, "sign_batch", result)


def test_dropping_several_files_shows_the_list(make_view, qtbot, fake_backend, tmp_path):
    paths = _files(tmp_path, ["a.bin", "b.bin", "c.bin"])

    view = make_view(sign_view.SignView)
    assert view._files.isHidden() is True

    view.load_many(paths)

    assert view._files.isHidden() is False
    assert view._files.paths() == paths
    assert view._button.text() == "Firmar los 3"


def test_one_file_keeps_the_simple_screen(make_view, qtbot, fake_backend, tmp_path):
    view = make_view(sign_view.SignView)
    view.load_many(_files(tmp_path, ["a.bin"]))

    assert view._files.isHidden() is True
    assert view._button.text() == "Firmar"


def test_the_same_file_twice_counts_once(make_view, qtbot, fake_backend, tmp_path):
    path = _files(tmp_path, ["a.bin"])[0]
    view = make_view(sign_view.SignView)
    view.load_many([path, path])
    assert view._files.paths() == [path]


def test_too_many_files_is_refused_rather_than_attempted(make_view, qtbot, fake_backend):
    """A stray select-all in a home directory should not become a card session."""
    view = make_view(sign_view.SignView)
    view.load_many([f"/tmp/f{i}.bin" for i in range(500)])

    assert view._button.isEnabled() is False
    assert "máximo es 200" in widget_text(view._status)


def test_one_file_goes_through_sign_file_and_many_through_sign_batch(
    make_view, qtbot, fake_backend, monkeypatch, tmp_path,
):
    fake_backend.patch(sign_view, "sign_file",
                       backend.SignResult(True, "/tmp/a.bin.p7s", "/tmp/a.bin.p7s"))
    _patch_batch(fake_backend, backend.BatchSignResult(True, []))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load_many(_files(tmp_path, ["a.bin"]))
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()
    assert [name for name, *_ in fake_backend.calls] == ["sign_file"]

    view.load_many(_files(tmp_path, ["b.bin", "c.bin"]))
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()
    assert "sign_batch" in [name for name, *_ in fake_backend.calls]


def test_progress_marks_each_file_as_it_is_written(make_view, qtbot, fake_backend, monkeypatch,
                                                   tmp_path):
    paths = _files(tmp_path, ["a.bin", "b.bin"])

    def fake(items, *, pin_provider, progress, **kw):
        for path in items:
            progress(backend.SignedItem(path, path + ".p7s", "signed"))
        return backend.BatchSignResult(
            True, [backend.SignedItem(p, p + ".p7s", "signed") for p in items])

    fake_backend.patch(sign_view, "sign_batch", side_effect=fake)
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load_many(paths)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert _status(view, 0) == "signed"
    assert _status(view, 1) == "signed"
    assert "Se firmaron los 2" in widget_text(view._status)


def test_a_partial_batch_says_what_survived(make_view, qtbot, fake_backend, monkeypatch,
                                            tmp_path):
    """The sentence that matters: those files were signed and are still on disk.

    Signed and still there, not valid. The self-check that would license the stronger word is a
    setting the person can turn off, so the screen says what it knows.
    """
    paths = _files(tmp_path, ["a.bin", "b.bin", "c.bin"])
    items = [
        backend.SignedItem(paths[0], paths[0] + ".p7s", "signed"),
        backend.SignedItem(paths[1], "", "failed", "Ya existe b.bin.p7s."),
        backend.SignedItem(paths[2]),
    ]
    _patch_batch(fake_backend, backend.BatchSignResult(
        False, items, "Ya existe b.bin.p7s.", "output_exists"))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load_many(paths)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert "Se firmaron 1 de 3" in widget_text(view._status)
    assert "quedaron guardados" in widget_text(view._survivors)
    # Good news inside bad news, each with its own tone. One shared message would have to pick a
    # side, and either colour would misdescribe half of what the screen is saying.
    assert view._status.property("tone") == "bad"
    assert view._survivors.property("tone") == "ok"
    assert _status(view, 0) == "signed"
    assert _status(view, 1) == "failed"
    assert _status(view, 2) == "pending"                  # never attempted
    assert view._open_btn.isHidden() is False             # the survivors are reachable


def test_the_screen_survives_a_batch_whose_only_output_is_warned(
    make_view, qtbot, fake_backend, monkeypatch, tmp_path,
):
    """A file written with the wrong permissions is written, and the screen has to agree.

    ``BatchSignResult.signed`` counts a warned item, because warned means the output exists and
    only its mode is pending. The screen looked for ``status == "signed"`` instead, so a batch
    whose first file hit OutputCommittedError left `signed` saying one and the search finding
    none. Measured: a bare ``next()`` raised StopIteration out of a UI slot, which is the one
    place the activity record cannot see, since it hangs off Task.run on the worker thread.
    """
    paths = _files(tmp_path, ["a.bin"])
    items = [backend.SignedItem(paths[0], paths[0] + ".p7s", "warned",
                                "Se firmó y quedó guardado, pero no se pudo ajustar el modo.")]
    _patch_batch(fake_backend, backend.BatchSignResult(
        False, items, "Se firmó y quedó guardado, pero no se pudo ajustar el modo.",
        "output_committed"))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load_many(paths + _files(tmp_path, ["b.bin"]))
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert _status(view, 0) == "warned"
    assert "quedaron guardados" in widget_text(view._survivors)
    assert view._open_btn.isHidden() is False
    assert view._output_path == paths[0] + ".p7s"          # and it opens the file that exists


def test_the_open_button_points_at_the_newest_output_even_when_it_is_warned(
    make_view, qtbot, fake_backend, monkeypatch, tmp_path,
):
    """The quieter half of the same disagreement, which crashed nothing and lied anyway.

    With [signed, signed, warned] the old search walked back past the warned one and stopped at
    the second, so "Abrir" opened a file the person had signed a moment earlier while the newest
    one sat there untouched.
    """
    paths = _files(tmp_path, ["a.bin", "b.bin", "c.bin"])
    items = [
        backend.SignedItem(paths[0], paths[0] + ".p7s", "signed"),
        backend.SignedItem(paths[1], paths[1] + ".p7s", "signed"),
        backend.SignedItem(paths[2], paths[2] + ".p7s", "warned", "Faltó ajustar el modo."),
    ]
    _patch_batch(fake_backend, backend.BatchSignResult(
        False, items, "Faltó ajustar el modo.", "output_committed"))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load_many(paths)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert view._output_path == paths[2] + ".p7s"


def test_a_batch_that_produced_nothing_offers_no_button_to_open_it(
    make_view, qtbot, fake_backend, monkeypatch, tmp_path,
):
    """The other end of the same helper: no output means no button, not a button onto "" ."""
    paths = _files(tmp_path, ["a.bin", "b.bin"])
    items = [backend.SignedItem(paths[0], "", "failed", "No se pudo."),
             backend.SignedItem(paths[1])]
    _patch_batch(fake_backend, backend.BatchSignResult(False, items, "No se pudo.", "sign"))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load_many(paths)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert view._open_btn.isHidden() is True
    assert widget_text(view._survivors) == ""


def test_a_refused_drop_clears_the_last_report(make_view, qtbot, fake_backend, monkeypatch,
                                               tmp_path):
    """The report is about a run that finished. Under "son 500 y el máximo es 200" it puts a
    signed file on screen next to a message about files that were never accepted."""
    fake_backend.patch(sign_view, "sign_file", backend.SignResult(
        True, "/tmp/doc.pdf.p7s", "/tmp/doc.pdf.p7s", kind="pades"))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load("/tmp/doc.pdf")
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()
    assert widget_text(view._report) != ""

    view.load_many([f"/tmp/{i}.pdf" for i in range(201)])

    assert "máximo es 200" in widget_text(view._status)
    assert widget_text(view._report) == ""


def test_the_reassurance_does_not_outlive_the_run_it_belonged_to(make_view, qtbot, fake_backend,
                                                                 monkeypatch, tmp_path):
    """"Los archivos ya firmados quedaron guardados" is only true about the run that produced it.

    Left on screen over a batch that saved nothing, the one sentence meant to stop somebody
    panicking becomes the one telling them a lie.
    """
    paths = _files(tmp_path, ["a.bin", "b.bin"])
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    _patch_batch(fake_backend, backend.BatchSignResult(
        False, [backend.SignedItem(paths[0], paths[0] + ".p7s", "signed"),
                backend.SignedItem(paths[1], "", "failed", "Ya existe.")],
        "Ya existe.", "output_exists"))
    view = make_view(sign_view.SignView)
    view.load_many(paths)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()
    assert "quedaron guardados" in widget_text(view._survivors)

    _patch_batch(fake_backend, backend.BatchSignResult(
        False, [backend.SignedItem(p) for p in paths], "No hay lector.", "no_reader"))
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert view._survivors.isHidden() is True
    assert widget_text(view._survivors) == ""


# --- the conflicts, decided before the PIN ----------------------------------

def test_conflicts_are_resolved_before_the_card_is_touched(make_view, qtbot, fake_backend,
                                                           monkeypatch, tmp_path):
    paths = _files(tmp_path, ["a.bin", "b.bin"])
    (tmp_path / "b.bin.p7s").write_bytes(b"ya firmado")

    asked = []
    monkeypatch.setattr(sign_view, "confirm_batch_conflicts",
                        lambda parent, conflicts, total: asked.append((conflicts, total)) or "skip")
    _patch_batch(fake_backend, backend.BatchSignResult(True, []))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load_many(paths)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    conflicts, total = asked[0]
    assert [src for src, _out in conflicts] == [paths[1]]
    assert total == 2
    # Only the clean one was sent, and the skipped row says why.
    assert fake_backend.calls[-1][1][0] == [paths[0]]
    assert "ya estaba firmado" in view._files.item(1).text()


def test_choosing_to_replace_sends_everything_with_overwrite(make_view, qtbot, fake_backend,
                                                             monkeypatch, tmp_path):
    paths = _files(tmp_path, ["a.bin", "b.bin"])
    (tmp_path / "b.bin.p7s").write_bytes(b"ya firmado")

    monkeypatch.setattr(sign_view, "confirm_batch_conflicts",
                        lambda parent, conflicts, total: "overwrite")
    _patch_batch(fake_backend, backend.BatchSignResult(True, []))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load_many(paths)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert fake_backend.calls[-1][1][0] == paths
    assert fake_backend.kwargs_for("sign_batch")["overwrite"] is True


def test_cancelling_the_conflict_dialog_never_reaches_the_card(make_view, qtbot, fake_backend,
                                                               monkeypatch, tmp_path):
    paths = _files(tmp_path, ["a.bin", "b.bin"])
    (tmp_path / "b.bin.p7s").write_bytes(b"ya firmado")

    monkeypatch.setattr(sign_view, "confirm_batch_conflicts",
                        lambda parent, conflicts, total: "cancel")
    _patch_batch(fake_backend, backend.BatchSignResult(True, []))
    monkeypatch.setattr(sign_view, "ask_pin",
                        lambda parent, **kw: pytest.fail("the PIN must never be asked"))

    view = make_view(sign_view.SignView)
    view.load_many(paths)
    view._on_sign()

    assert fake_backend.calls == []
    assert view._card.busy is False
    assert "No se firmó nada" in widget_text(view._status)


def test_a_clean_batch_asks_nothing(make_view, qtbot, fake_backend, monkeypatch, tmp_path):
    monkeypatch.setattr(sign_view, "confirm_batch_conflicts",
                        lambda parent, conflicts, total: pytest.fail("must not be asked"))
    _patch_batch(fake_backend, backend.BatchSignResult(True, []))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load_many(_files(tmp_path, ["a.bin", "b.bin"]))
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert fake_backend.kwargs_for("sign_batch")["overwrite"] is False


# --- the drop area ----------------------------------------------------------

def test_a_drop_keeps_only_real_local_files(tmp_path):
    """A drop carries anything: a remote URL, whose toLocalFile is empty, or a folder, which
    would otherwise travel all the way into firmauy before being rejected."""
    from PySide6.QtCore import QUrl

    from firmauy_desktop.widgets import local_files

    real = tmp_path / "doc.pdf"
    real.write_bytes(b"x")
    folder = tmp_path / "carpeta"
    folder.mkdir()

    urls = [QUrl.fromLocalFile(str(real)), QUrl.fromLocalFile(str(folder)),
            QUrl("https://ejemplo.uy/doc.pdf"), QUrl.fromLocalFile(str(tmp_path / "no-existe"))]

    assert local_files(urls) == [str(real)]


def test_a_batch_reduced_to_one_file_stays_a_batch(make_view, qtbot, fake_backend, monkeypatch,
                                                   tmp_path):
    """Regression. The branch used to be decided after the pre-flight, so skipping two of three
    fell into the single-file path, which called a function that test had not replaced and ran a
    real signature against a real cédula. It is decided by what was dropped now.
    """
    paths = _files(tmp_path, ["a.bin", "b.bin", "c.bin"])
    for name in ("b.bin.p7s", "c.bin.p7s"):
        (tmp_path / name).write_bytes(b"ya firmado")

    monkeypatch.setattr(sign_view, "confirm_batch_conflicts",
                        lambda parent, conflicts, total: "skip")
    _patch_batch(fake_backend, backend.BatchSignResult(
        True, [backend.SignedItem(paths[0], paths[0] + ".p7s", "signed")]))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load_many(paths)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert [name for name, *_ in fake_backend.calls] == ["sign_batch"]
    assert view._files.isHidden() is False               # still a list, not a single-file report
    assert _status(view, 1) == "skipped"                 # skipped, and said so


def test_the_guard_catches_a_view_reaching_the_real_backend(make_view, qtbot):
    """A meta-test for conftest's net. Without it, an unanticipated code path in a screen ends
    up at the card with whatever PIN the test made up, which spends one of its limited tries."""
    view = make_view(sign_view.SignView)
    with pytest.raises(AssertionError, match="called the real backend"):
        sign_view.sign_file("/tmp/doc.pdf", pin_provider=lambda: "1234")
    del view


# --- cancelling a long batch ------------------------------------------------

def test_the_cancel_button_only_shows_for_a_batch(make_view, qtbot, fake_backend, monkeypatch,
                                                  tmp_path):
    """firmauy checks between files, so with one file there is nothing to stop before."""
    fake_backend.patch(sign_view, "sign_file",
                       backend.SignResult(True, "/tmp/a.p7s", "/tmp/a.p7s"))
    _patch_batch(fake_backend, backend.BatchSignResult(True, []))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load_many(_files(tmp_path, ["a.bin"]))
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()
        assert view._cancel_btn.isHidden() is True       # nothing to cancel

    view.load_many(_files(tmp_path, ["b.bin", "c.bin"]))
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()
        assert view._cancel_btn.isHidden() is False
    assert view._cancel_btn.isHidden() is True           # gone once it settled


def test_cancelling_stops_the_batch_at_the_next_file(make_view, qtbot, fake_backend, monkeypatch,
                                                     tmp_path):
    paths = _files(tmp_path, ["a.bin", "b.bin", "c.bin"])
    signed = []
    holder = {}

    def fake(items, *, pin_provider, progress, should_continue, **kw):
        for path in items:
            if not should_continue():
                break                                    # asked between files, as firmauy does
            signed.append(path)
            progress(backend.SignedItem(path, path + ".p7s", "signed"))
            holder["view"]._stop.set()                   # Cancelar, pressed after the first one
        return backend.BatchSignResult(
            False, [backend.SignedItem(p, p + ".p7s", "signed") for p in signed]
            + [backend.SignedItem(p) for p in items[len(signed):]],
            "", "cancelled")

    fake_backend.patch(sign_view, "sign_batch", side_effect=fake)
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    holder["view"] = view
    view.load_many(paths)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert signed == paths[:1]                           # it stopped at the next boundary
    assert "Cancelado. Se firmaron 1 de 3" in widget_text(view._status)
    assert "quedaron guardados" in widget_text(view._survivors)


def test_a_cancelled_batch_says_what_was_kept(make_view, qtbot, fake_backend, monkeypatch,
                                              tmp_path):
    """The person chose to stop, and still needs to know which files are signed and where."""
    paths = _files(tmp_path, ["a.bin", "b.bin", "c.bin"])
    _patch_batch(fake_backend, backend.BatchSignResult(False, [
        backend.SignedItem(paths[0], paths[0] + ".p7s", "signed"),
        backend.SignedItem(paths[1]),
        backend.SignedItem(paths[2]),
    ], "", "cancelled"))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load_many(paths)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert "Cancelado. Se firmaron 1 de 3" in widget_text(view._status)
    assert "quedaron guardados" in widget_text(view._survivors)
    assert view._open_btn.isHidden() is False
    assert _status(view, 0) == "signed"


def test_the_cancel_button_promises_only_what_it_can_do(make_view, qtbot, fake_backend,
                                                        tmp_path):
    """An output is written whole or not at all, so an instant stop would be a lie."""
    view = make_view(sign_view.SignView)
    view.load_many(_files(tmp_path, ["a.bin", "b.bin"]))
    view._on_cancel()

    assert view._stop.is_set() is True
    assert view._cancel_btn.isEnabled() is False         # cannot be pressed twice
    assert "Termina el archivo" in widget_text(view._status)


def test_shutdown_asks_a_batch_to_stop(make_view, qtbot, fake_backend, tmp_path):
    """Closing the window should not work through the rest of the queue first."""
    view = make_view(sign_view.SignView)
    view.load_many(_files(tmp_path, ["a.bin", "b.bin"]))
    view.shutdown()

    assert view._stop.is_set() is True


def test_the_stop_flag_is_cleared_before_each_run(make_view, qtbot, fake_backend, monkeypatch,
                                                  tmp_path):
    """A cancel must not leak into the next batch."""
    _patch_batch(fake_backend, backend.BatchSignResult(True, []))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load_many(_files(tmp_path, ["a.bin", "b.bin"]))
    view._on_cancel()
    assert view._stop.is_set() is True

    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()
    assert view._stop.is_set() is False


def test_sign_batch_forwards_the_callback(monkeypatch, tmp_path):
    captured = {}

    def fake(items, **kw):
        captured.update(kw)
        return []

    monkeypatch.setattr(backend, "_api_sign_files", fake)
    backend.sign_batch(_files(tmp_path, ["a.bin"]), pin_provider=lambda: "1234",
                       should_continue=lambda: False, allow_private_network=True)

    assert callable(captured["should_continue"])
    assert captured["allow_private_network"] is True


def test_a_cancelled_batch_is_not_reported_as_an_error(monkeypatch, tmp_path):
    """Somebody pressing cancel is not something going wrong, so there is no message to show."""
    from firmauy.api import BatchSignCancelled, SignReport

    paths = _files(tmp_path, ["a.bin", "b.bin"])

    def fake(items, *, pin_provider, progress, **kw):
        out = Path(items[0] + ".p7s")
        out.write_bytes(b"firma")
        progress(0, Path(items[0]), out)
        raise BatchSignCancelled(
            "cancelled", completed=[SignReport(output_path=out, signer="X", issuer="Y")],
            stopped_before=1)

    monkeypatch.setattr(backend, "_api_sign_files", fake)

    result = backend.sign_batch(paths, pin_provider=lambda: "1234")

    assert result.error_kind == "cancelled"
    assert result.error == ""                            # nothing went wrong
    assert result.signed == 1
    assert result.items[1].status == "pending"


def test_the_batch_says_how_far_along_it_is(make_view, qtbot, fake_backend, monkeypatch,
                                            tmp_path):
    """It used to say "Firmando... (factura.pdf)". Signing twenty-four files, the names flicker
    past and nothing says how much is left, though the app has both numbers and throws one away.
    """
    paths = _files(tmp_path, ["a.bin", "b.bin", "c.bin"])
    items = [backend.SignedItem(p, p + ".p7s", "signed") for p in paths]

    def fake_batch(sources, *, progress, **kw):
        for item in items:
            progress(item)
        return backend.BatchSignResult(True, items)

    fake_backend.patch(sign_view, "sign_batch", side_effect=fake_batch)
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load_many(paths)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert view._batch_done == 3
    assert view._batch_total == 3
    assert view._progress.maximum() == 3


def test_the_total_is_what_was_signed_not_what_was_dropped(make_view, qtbot, fake_backend,
                                                           monkeypatch, tmp_path):
    """The pre-flight can drop files. Counting against what was dropped would leave the bar
    short of the end every time somebody chose to skip an existing output."""
    paths = _files(tmp_path, ["a.bin", "b.bin", "c.bin"])
    (tmp_path / "b.bin.p7s").write_bytes(b"ya firmado")
    (tmp_path / "c.bin.p7s").write_bytes(b"ya firmado")

    monkeypatch.setattr(sign_view, "confirm_batch_conflicts",
                        lambda parent, conflicts, total: "skip")
    _patch_batch(fake_backend, backend.BatchSignResult(True, []))
    monkeypatch.setattr(sign_view, "ask_pin", lambda parent, **kw: "1234")

    view = make_view(sign_view.SignView)
    view.load_many(paths)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_sign()

    assert view._batch_total == 1        # one survived the pre-flight, not three


def test_a_committed_output_is_not_reported_as_a_failure(monkeypatch, tmp_path):
    """firmauy 1.14.0 raises OutputCommittedError when the signature is written and in place and
    only its permissions could not be set. The file exists, so calling the row "falló" tells
    somebody a document was never produced while it sits there complete, and the obvious response
    to that is to sign it a second time."""
    paths = _files(tmp_path, ["a.bin", "b.bin"])

    def fake(items, *, pin_provider, progress, **kw):
        out = Path(items[0] + ".p7s")
        out.write_bytes(b"firma")
        progress(0, Path(items[0]), out)          # 1.14.0 announces it: the output is written
        raise BatchSignError(
            "stopped", completed=[SignReport(output_path=out, signer="X", issuer="Y")],
            failed_index=0, failed_path=Path(items[0]),
        ) from OutputCommittedError("mode", path=out, final_mode=0o644, errno=30)

    monkeypatch.setattr(backend, "_api_sign_files", fake)

    result = backend.sign_batch(paths, pin_provider=lambda: "1234")

    assert result.items[0].status == "warned", "a signed file was reported as failed"
    assert result.items[0].output_path.endswith("a.bin.p7s")
    assert result.signed == 1, "it exists, so it counts"
    assert result.error_kind == "output_committed"
    assert "lo que falta son los permisos, no otra firma" in result.items[0].detail
    assert result.conflict_path == "", "nothing is in the way: that file is meant to be there"


@pytest.mark.parametrize("outcome,covers,expected", [
    ("failed", None, "Borralo y firmá de nuevo"),
    ("detached-mismatch", "a.bin", "firmaría a.bin tal como está hoy"),
    ("inconclusive", None, "no se sabe si la firma está bien o mal"),
])
def test_each_verification_outcome_says_something_different(monkeypatch, tmp_path, outcome,
                                                            covers, expected):
    """One class with a field, because the answers are opposite: one says delete this and sign
    again, and the other two say specifically not to. A single sentence for all three would leave
    the person to guess which one they got."""
    paths = _files(tmp_path, ["a.bin"])
    out = Path(paths[0] + ".p7s")

    def fake(items, *, pin_provider, progress, **kw):
        raise BatchSignError("stopped", completed=[], failed_index=0,
                             failed_path=Path(items[0])) from PostSignVerificationError(
            "x", path=out, outcome=outcome,
            covers=Path(tmp_path / covers) if covers else None)

    monkeypatch.setattr(backend, "_api_sign_files", fake)

    result = backend.sign_batch(paths, pin_provider=lambda: "1234")

    assert result.error_kind == "verify_failed"
    assert expected in result.error
    assert result.items[0].status == "failed", "nothing usable came out of this one"
    assert result.conflict_path == ""


def test_access_control_refusal_says_nothing_was_written(monkeypatch, tmp_path):
    """The one that leaves no file. Replacing the output would have changed who could read it, so
    firmauy refused before writing and the file that was there is untouched."""
    paths = _files(tmp_path, ["a.bin"])

    def fake(items, *, pin_provider, progress, **kw):
        raise OutputAccessControlError("no", path=Path(items[0] + ".p7s"))

    monkeypatch.setattr(backend, "_api_sign_files", fake)

    result = backend.sign_batch(paths, pin_provider=lambda: "1234")

    assert result.error_kind == "access_control"
    assert "no se escribió nada" in result.error
    assert result.conflict_path == "", "an overwrite prompt would be the wrong offer here"


def test_the_file_list_shows_whole_rows(qtbot):
    """A list that ends mid-row reads as the app having lost a file, not as one that scrolls.

    The height used to come from `rows_high`, which measures the font and was written for the drop
    area: 14 points of text against a 32 point row, so eight rows asked for showed 3.4 and the
    fourth file of four was sliced through the middle."""
    from firmauy_desktop.widgets import FileListWidget

    widget = FileListWidget()
    qtbot.addWidget(widget)
    widget.set_paths([f"/tmp/acta-{n}.pdf" for n in range(1, 13)])
    widget.resize(700, widget.maximumHeight())
    widget.show()

    row = widget.sizeHintForRow(0)
    assert row > 0
    fits = widget.viewport().height() / row
    assert fits == pytest.approx(FileListWidget.VISIBLE_ROWS, abs=0.05), (
        f"shows {fits:.2f} rows where {FileListWidget.VISIBLE_ROWS} were asked for")


def test_four_files_do_not_need_a_scrollbar(qtbot):
    """The case in the screenshots: four files, and the fourth cut in half with a scrollbar
    beside it, which is the worst way to see this."""
    from firmauy_desktop.widgets import FileListWidget

    widget = FileListWidget()
    qtbot.addWidget(widget)
    widget.set_paths([f"/tmp/acta-{n}.pdf" for n in range(1, 5)])
    widget.resize(700, widget.maximumHeight())
    widget.show()

    assert widget.verticalScrollBar().maximum() == 0, "four files should not scroll"
    last = widget.visualItemRect(widget.item(3))
    assert last.bottom() <= widget.viewport().height(), "the last row is cut off"
