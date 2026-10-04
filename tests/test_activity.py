# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""The activity record keeps its two promises, or it should not exist.

It is the only thing in this app that leaves a trace on disk, and the app's whole posture is the
opposite: SECURITY.md names "a log" among the places the PIN must never reach, and settings.py
refuses a recent-files list because it would put the holder's document names somewhere that
outlives the uninstall. So there are two promises, and both are held here mechanically rather
than by reading the call sites.

Off writes nothing at all. On writes the shape of what happened and never the subject.

The fixtures deliberately carry hostile values, a real-looking cardholder and a path that says
what the document is about, so their absence from the file proves the redaction ran rather than
that there was nothing to redact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from firmauy_desktop import activity, backend

HOLDER = "PERSONA DE PRUEBA PEREZ"
DOCUMENT = "/home/juana/contrato-divorcio.pdf"
PIN = "4321"


def _text() -> str:
    path = activity.log_path()
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def test_off_writes_nothing_at_all(qapp):
    """The whole point of opt-in. Not an empty file, not a directory: nothing."""
    activity.configure(False)
    activity.event("firma", kind="pades")
    activity.crash(RuntimeError("boom"))

    assert not activity.log_path().exists()
    assert not activity.log_path().parent.exists()


def test_a_field_nobody_declared_is_replaced_name_and_all(qapp):
    """The last channel that was the caller's. Python does not require a keyword to look like an
    identifier, so ``event("firma", **{"contrato-divorcio.pdf": 1})`` is a legal call, and
    checking the value while copying the key destroyed one half of the pair and wrote the rest.
    """
    activity.configure(True)
    activity.event("firma", **{"PEREZ": 1, "contrato-divorcio.pdf": 2, DOCUMENT: 3})

    written = _text()
    assert "PEREZ" not in written
    assert "contrato-divorcio" not in written
    assert "juana" not in written and DOCUMENT not in written
    assert written.count(activity.UNDECLARED) == 3


def test_the_declared_vocabulary_still_goes_through(qapp):
    """A record that refuses everything is not a record. The three closed sets have to let the
    language they were built for pass."""
    activity.configure(True)
    activity.event("firma lista", kind="pades", backend="native", verified=True)

    written = _text()
    assert "firma lista" in written
    assert "kind=pades" in written and "backend=native" in written and "verified=True" in written
    assert activity.REDACTED not in written


def test_signing_records_the_shape_and_never_the_document(qapp, monkeypatch, tmp_path):
    """The end to end promise, through the real backend seam rather than by calling event()."""
    from firmauy.api import SignReport

    document = tmp_path / "contrato-divorcio.pdf"
    document.write_bytes(b"%PDF-1.7\n")

    def fake(path, pin=None, **kw):
        return SignReport(output_path=document, signer=HOLDER, issuer="AC RAIZ NACIONAL",
                          kind="pades", backend="native", certificate_serial="0123ABCD",
                          verified=True)

    monkeypatch.setattr(backend, "_api_sign", fake)
    activity.configure(True)
    result = backend.sign_file(str(document), PIN, native=True)

    assert result.ok is True
    written = _text()
    # What it must know: that a PAdES signature was made natively and checked afterwards.
    assert "kind=pades" in written
    assert "backend=native" in written
    assert "verified=True" in written
    # What it must not: who, which document, or which certificate.
    for secret in (HOLDER, "PEREZ", "contrato-divorcio", "0123ABCD", str(tmp_path)):
        assert secret not in written, f"{secret!r} reached the activity record"


def test_the_pin_never_reaches_the_file(qapp, monkeypatch, tmp_path):
    """SECURITY.md lists "a log" among the places the PIN may not go, so it gets its own test
    rather than riding along with the rest."""
    document = tmp_path / "d.pdf"
    document.write_bytes(b"%PDF-1.7\n")

    def fake(path, pin=None, *, pin_provider=None, **kw):
        if pin_provider is not None:
            pin_provider()                      # firmauy asks, exactly as it would
        raise RuntimeError("la tarjeta no respondió")

    monkeypatch.setattr(backend, "_api_sign", fake)
    activity.configure(True)
    backend.sign_file(str(document), pin_provider=lambda: PIN, native=True)

    written = _text()
    assert PIN not in written
    assert "firma falló" in written             # the failure was recorded, so this can fail


def test_a_crash_keeps_where_it_broke_and_says_nothing_of_what(qapp):
    """The crash path is why this exists: the packaged build sets console=False, so the traceback
    PySide6 prints has nowhere to go on Windows or macOS.

    The message is left out on purpose. It used to be written through the scrubber, and that
    filter only knows what a path looks like: measured, "falló contrato-divorcio.pdf de JUANA
    PEREZ" survived whole and a path containing a space left "de divorcio.pdf" behind. Those
    strings come from pyHanko, cryptography and Qt rather than from this app, so no filter over
    them can hold up a promise. What stays is the class of failure and the line it came from.
    """
    activity.configure(True)
    try:
        raise FileNotFoundError(2, "no such file", f"{DOCUMENT} de {HOLDER}")
    except FileNotFoundError as exc:
        activity.crash(exc)

    written = _text()
    assert "FileNotFoundError" in written
    assert "errno=2" in written, "the one property worth keeping, and it is an integer"
    # Nothing of the message, whatever it happened to hold.
    for secret in (DOCUMENT, "juana", "contrato-divorcio", HOLDER, "no such file"):
        assert secret not in written, f"{secret!r} reached the activity record"
    # This file is not inside the package, so its frame is counted rather than named.
    assert "test_activity.py" not in written
    assert "fuera de la app" in written


def test_a_crash_names_the_frames_inside_the_app_and_counts_the_rest(qapp):
    """A frame's file name is whatever its code object was compiled with, so naming every frame
    let anything into the record: `compile(src, "contrato-divorcio.pdf")` was enough. Frames from
    this program are named, because where a crash entered the app is what makes it reproducible,
    and everything else is a tally.
    """
    from firmauy_desktop.tasks import Task

    activity.configure(True)
    task = Task(lambda: (_ for _ in ()).throw(ValueError("x")))
    with pytest.raises(ValueError):
        task.run()

    written = _text()
    assert "tasks.py:" in written, "the app's own frame is what makes a crash reproducible"
    assert "fuera de la app" in written, "and the lambda in this file is counted, not named"


def test_a_frame_compiled_with_any_name_is_never_written(qapp):
    """The reason the frames are filtered rather than trusted."""
    activity.configure(True)
    try:
        exec(compile("raise RuntimeError('x')", "/home/juana/contrato-divorcio.pdf", "exec"))
    except RuntimeError as exc:
        activity.crash(exc)

    written = _text()
    assert "contrato-divorcio" not in written and "juana" not in written
    assert "crash  RuntimeError" in written      # still recorded, so this can fail


def test_a_class_name_this_record_cannot_place_is_not_written(qapp):
    """__name__ is metadata like any other: a class built at run time carries whatever name it
    was given. The set of names comes from the interpreter and from firmauy, never from the
    exception itself."""
    activity.configure(True)
    for exc in (type("PEREZ_12345678", (Exception,), {})("x"), ValueError("x")):
        try:
            raise exc
        except Exception as raised:
            activity.crash(raised)

    written = _text()
    assert "PEREZ_12345678" not in written
    assert "crash  Exception" in written, "an unplaceable class still says a crash happened"
    assert "crash  ValueError" in written, "and a builtin is still named"


@pytest.mark.parametrize("exc", [
    type("Explota", (Exception,), {"errno": property(lambda self: 1 / 0)})("x"),
    type("Raro", (OSError,), {"errno": property(lambda self: "no soy un número")})("x"),
])
def test_reading_errno_can_never_take_the_crash_with_it(exc):
    """tasks.py records a crash and then re-raises, so an exception escaping from in here would
    replace the one it was trying to write down and lose the bug and the record together. errno
    is read off OSError's own descriptor rather than through getattr, which runs whatever the
    class put there."""
    assert activity._errno(exc) is None


def test_a_message_no_filter_could_recognise_is_still_never_written(qapp):
    """The three shapes that measured through the filter this module used to have, kept as a
    regression: a bare file name, a path with a space in it, and a cédula number. None of them was
    path-shaped enough for it, which is why guessing was replaced by not writing the message."""
    activity.configure(True)
    for message in (f"falló contrato-divorcio.pdf de {HOLDER}",
                    "no se pudo abrir /home/juana/Contrato de divorcio.pdf",
                    "cédula 1.234.567-8 rechazada"):
        try:
            raise RuntimeError(message)
        except RuntimeError as exc:
            activity.crash(exc)

    written = _text()
    assert written.count("crash  RuntimeError") == 3, "the crashes were recorded at all"
    for secret in ("contrato-divorcio", "JUANA", "juana", "divorcio.pdf", "1.234.567-8"):
        assert secret not in written


def test_a_crash_is_recorded_and_still_escapes(qapp):
    """tasks.py documents that nothing may be swallowed there: the exception has to keep going so
    pytest-qt turns it into a failed test. Recording it must not quietly change that."""
    from firmauy_desktop.tasks import Task

    activity.configure(True)
    task = Task(lambda: (_ for _ in ()).throw(ValueError("se rompió")))

    with pytest.raises(ValueError, match="se rompió"):
        task.run()

    assert "crash  ValueError" in _text()
    assert "se rompió" not in _text(), "the message is not this record's to keep"


def test_the_record_does_not_grow_without_end(qapp, monkeypatch):
    """A file somebody has to be talked through truncating is a file that grows forever."""
    monkeypatch.setattr(activity, "MAX_BYTES", 2048)
    activity.configure(True)
    for index in range(400):
        activity.event("firma", n=index)

    rotated = activity.written_files()
    assert len(rotated) == 1 + activity.BACKUPS
    assert all(path.stat().st_size < 2048 * 3 for path in rotated)


def test_turning_it_off_leaves_what_was_written(qapp):
    """Somebody who reproduced a problem and then switched the setting would otherwise lose the
    very thing they were about to send. Ajustes has a button for deleting, where that is the
    thing being asked for."""
    activity.configure(True)
    activity.event("firma lista", kind="pades")
    activity.configure(False)

    assert "firma lista" in _text()
    assert activity.written_files()


def test_deleting_the_record_keeps_recording_into_a_file_that_exists(qapp):
    """The ordinary flow this button is for: turn it on, clear it, keep using the app, send it.

    Measured before the delete belonged to this module: Ajustes unlinked the files while the
    handler still had one open, so the name left the directory and the descriptor kept pointing
    at the inode. Everything after the delete went in there, a crash among it. The button
    reported success, Ajustes showed a path with nothing at it, and the person who cleared the
    record precisely so they could reproduce a problem cleanly had no file to attach.
    """
    activity.configure(True)
    activity.event("firma", kind="pades", backend="native")

    assert activity.clear() == 1

    activity.event("firma lista", kind="pades", backend="native", verified=True)
    activity.crash(RuntimeError("boom"))

    written = _text()                    # by way of log_path(), which an unnamed inode has not
    assert activity.log_path().is_file()
    assert "registro iniciado" in written
    assert "firma lista" in written and "crash  RuntimeError" in written
    assert "firma  kind=pades" not in written        # and the entry from before it is gone


def test_deleting_with_the_record_off_starts_nothing(qapp):
    """The button is reachable with the setting off, and off keeps meaning off: clearing a
    record nobody is keeping is not a reason to open one."""
    activity.configure(False)

    assert activity.clear() == 0
    assert not activity.log_path().exists()
    assert not activity.log_path().parent.exists()

    activity.event("firma", kind="pades")
    assert not activity.log_path().exists()


def test_deleting_takes_the_rotated_files_too(qapp, monkeypatch):
    """Rotation is what makes this more than one file, and half a delete is not a delete."""
    monkeypatch.setattr(activity, "MAX_BYTES", 2048)
    activity.configure(True)
    for index in range(400):
        activity.event("firma", n=index)
    assert len(activity.written_files()) == 1 + activity.BACKUPS

    removed = activity.clear()

    assert removed == 1 + activity.BACKUPS
    assert activity.written_files() == [activity.log_path()]
    assert _text().strip().endswith("registro iniciado")


def test_a_delete_that_refuses_leaves_the_record_running(qapp, monkeypatch):
    """A read-only state directory is the ordinary way this fails, and the message says so.

    What must not happen alongside it is the handler staying closed with the setting still
    switched on, which is a record that stopped working and told nobody. Hence the finally.
    """
    activity.configure(True)
    activity.event("firma", kind="pades", backend="native")

    def refuse(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied")

    with monkeypatch.context() as patched:              # scoped: the log_path patch is autouse
        patched.setattr(Path, "unlink", refuse)
        with pytest.raises(OSError):
            activity.clear()

    activity.event("firma lista", kind="pades")

    written = _text()
    assert "firma lista" in written                     # still recording
    assert "firma  kind=pades" in written               # and nothing was half-deleted


def test_it_keeps_a_count_and_no_number_that_identifies_anybody(qapp, monkeypatch, tmp_path):
    """The distinction the documents now state, made executable.

    "Never a number" was written in the module and in SECURITY.md, one sentence after saying the
    record keeps how many files were signed. Both were true of different numbers, and neither
    said which. A tally is what this exists for. A cédula is what it must never see.
    """
    from firmauy.api import SignReport

    paths = []
    for name in ("a.bin", "b.bin", "c.bin"):
        path = tmp_path / name
        path.write_bytes(b"x")
        paths.append(str(path))

    def fake(items, *, pin_provider, progress, **kw):
        for index, item in enumerate(items):
            out = Path(item + ".p7s")
            out.write_bytes(b"firma")
            progress(index, Path(item), out)
        return [SignReport(output_path=Path(item + ".p7s"), signer="PEREZ, JUANA 1.234.567-8",
                           issuer="AC RAIZ") for item in items]

    monkeypatch.setattr(backend, "_api_sign_files", fake)
    activity.configure(True)
    result = backend.sign_batch(paths, pin_provider=lambda: PIN)

    assert result.signed == 3
    written = _text()
    assert "total=3" in written, "the tally is the kind of number this record is for"
    assert "firmados=3" in written
    for identifying in ("1.234.567-8", "JUANA", "PEREZ"):
        assert identifying not in written, f"{identifying!r} is the kind it must never see"


def test_every_field_the_app_records_is_in_the_vocabulary():
    """The invariant the rest of this file could not reach by testing behaviour.

    event() takes **fields, so a line added tomorrow can name one this record has no domain for.
    Nothing does today, which is exactly the state a convention is in right before somebody
    breaks it. This reads the call sites instead of trusting them.

    Static rather than enforced inside event(): the risk is a line added to this repository, and
    a test catches that before it can ever run, while a check at run time has to choose between
    raising over a log entry and dropping a field in silence. Adding a name to VOCABULARY is the
    review step, turned into an edit somebody makes on purpose.
    """
    import ast
    from pathlib import Path as _Path

    src = _Path(__file__).resolve().parent.parent / "src" / "firmauy_desktop"
    used = {}
    for path in src.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "event"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "activity"):
                continue
            for keyword in node.keywords:
                used.setdefault(keyword.arg, f"{path.relative_to(src)}:{node.lineno}")

    assert used, "no activity.event call sites found at all, so this would pass on nothing"
    unknown = {name: where for name, where in used.items() if name not in activity.VOCABULARY}
    assert unknown == {}, f"fields outside the vocabulary: {unknown}"


def test_a_value_that_is_a_sentence_is_not_written(qapp):
    """The second layer, and a narrower one. It catches a person reaching a field that is allowed
    to exist, because names carry spaces and commas. It does not catch a bare file name, which is
    why the vocabulary is the layer that matters."""
    activity.configure(True)
    activity.event("firma", backend="PEREZ, JUANA 1.234.567-8", kind="pades", total=3)

    written = _text()
    assert "PEREZ" not in written and "1.234.567-8" not in written
    assert f"backend={activity.REDACTED}" in written
    assert "kind=pades" in written and "total=3" in written   # the vocabulary still goes through


@pytest.mark.parametrize("key,value,written", [
    ("backend", "native", "native"),            # the domain
    ("backend", "PEREZ", activity.REDACTED),    # a surname is one token, and fits no domain
    ("backend", "1.234.567-8", activity.REDACTED),
    ("kind", "contrato-divorcio.pdf", activity.REDACTED),
    ("sign_as", "auto", "auto"),
    ("indication", "VALID", "VALID"),
    ("error_kind", "pin", "pin"),
    ("total", 3, "3"),
    ("total", -1, activity.REDACTED),           # a count is not negative
    ("total", True, activity.REDACTED),         # nor is a boolean a count, though Python says so
    ("verify", True, "True"),
    ("verify", "sí", activity.REDACTED),
    ("holder", "cualquier cosa", activity.REDACTED),   # a field nobody declared says nothing
])
def test_each_field_is_held_to_its_own_domain(key, value, written):
    """Closing the field names was half of the rule. "1.234.567-8", "PEREZ" and "contrato.pdf"
    are each a single token, so a check about shape let all three through a field whose name
    happened to be allowed. What a field may hold is the other half."""
    assert activity._value(key, value) == written


def test_every_event_the_app_records_is_a_declared_literal():
    """The event name was free text and went through no check at all, so an f-string built from a
    file name would have written it. Checked twice: here by reading the call sites, which forces
    the vocabulary to be visible in the source, and in event() itself, which is what covers a call
    this pattern never sees.
    """
    import ast
    from pathlib import Path as _Path

    src = _Path(__file__).resolve().parent.parent / "src" / "firmauy_desktop"
    seen, bad = 0, {}
    for path in src.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "event"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "activity"):
                continue
            seen += 1
            first = node.args[0] if node.args else None
            where = f"{path.relative_to(src)}:{node.lineno}"
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                bad[where] = "built rather than written"
            elif first.value not in activity.EVENTS:
                bad[where] = first.value

    assert seen, "no activity.event call sites found at all, so this would pass on nothing"
    assert bad == {}, f"events outside the declared set: {bad}"


def test_the_error_kinds_match_what_the_backend_can_answer():
    """error_kind's domain is declared here because backend imports this module, so it cannot be
    imported back. A kind added there and not here would arrive redacted, which is the quiet way
    this record would start losing the one field that says what went wrong.
    """
    import ast
    from pathlib import Path as _Path

    source = (_Path(__file__).resolve().parent.parent / "src" / "firmauy_desktop"
              / "backend.py").read_text(encoding="utf-8")
    answers = {node.value.value
               for func in ast.walk(ast.parse(source))
               if isinstance(func, ast.FunctionDef) and func.name == "_kind"
               for node in ast.walk(func)
               if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant)}

    assert answers, "_kind returns no literals, which cannot be right"
    missing = answers - activity.ERROR_KINDS
    assert missing == set(), f"backend._kind can answer {missing} and the record would hide it"


def test_the_icon_names_match_the_files_that_ship():
    """Declared here because ui.icons imports this module and cannot be imported back. An icon
    added there and not here would be reported as [redactado], which is the quiet way the one
    field that says *which* icon is missing stops saying it."""
    from firmauy_desktop.ui import icons

    assert activity.ICON_NAMES == {path.stem for path in icons.ICON_DIR.glob("*.svg")}


@pytest.mark.parametrize("value", [[], {}, set(), object()])
def test_an_unhashable_value_is_redacted_and_not_raised(value):
    """`value in frozenset` raises on anything unhashable, so a list reaching a field with a
    domain would have ended the operation it was describing. A record that can do that is worse
    than no record, which this module says two lines above where it used to happen."""
    assert activity._value("backend", value) == activity.REDACTED
    assert activity._value("total", value) == activity.REDACTED


def test_an_undeclared_event_is_not_written_even_if_it_reaches_here(qapp):
    """The test that reads the call sites covers a line written in this package. This covers a
    call its pattern never saw: an aliased import, a `from activity import event`, or the module
    calling itself. The point is not catching the mistake, it is that nothing arbitrary lands in
    the file."""
    activity.configure(True)
    activity.event(f"firma falló /home/juana/contrato-divorcio.pdf")   # noqa: F541

    written = _text()
    assert activity.REDACTED in written
    assert "juana" not in written and "contrato-divorcio" not in written


def test_nothing_a_caller_can_pass_makes_the_record_raise(qapp):
    """"A record that can do that is worse than no record" has to survive a subclass, which is
    the one place in this app where type() is the right test instead of isinstance.

    A subclass defines __hash__ and __str__, so `value in allowed` and `str(value)` are both
    calls into somebody else's code and either can raise from inside the logger. Nothing
    legitimate arrives as one: these are literals out of a fixed vocabulary.
    """
    class Hostile(str):
        def __hash__(self):
            raise RuntimeError("desde __hash__")

    class Counting(int):
        def __str__(self):
            raise RuntimeError("desde __str__")

    assert activity._value("backend", Hostile("native")) == activity.REDACTED
    assert activity._value("total", Counting(3)) == activity.REDACTED
    assert activity._value("verify", Counting(1)) == activity.REDACTED

    activity.configure(True)
    activity.event(Hostile("firma"), backend=Hostile("native"))    # must not raise

    written = _text()
    assert activity.REDACTED in written
    assert "native" not in written


def test_the_firmauy_error_names_match_what_the_api_exports():
    """Declared here because activity is a leaf: backend imports it, so it cannot import back.
    One of these reaching crash() means backend broke its promise never to raise, which is the
    crash most worth naming precisely, and a class renamed upstream would quietly become
    "Exception"."""
    from firmauy import api

    exported = {name for name in dir(api)
                if isinstance(getattr(api, name), type)
                and issubclass(getattr(api, name), BaseException)}

    assert exported, "firmauy.api exports no exceptions, which cannot be right"
    assert exported <= activity.FIRMAUY_ERRORS, f"not named here: {exported - activity.FIRMAUY_ERRORS}"


def test_a_key_that_impersonates_a_declared_field_is_not_copied(qapp):
    """The left half of the pair, left behind when the values were closed. A str subclass gets to
    define __hash__ and __eq__, so it can compare equal to "backend" while its own text says
    something else, and the f-string writes the text. Measured: "PEREZ_12345678=native".
    """
    class Impostor(str):
        def __hash__(self):
            return hash("backend")

        def __eq__(self, other):
            return other == "backend"

    activity.configure(True)
    activity.event("firma", **{Impostor("PEREZ_12345678"): "native"})

    written = _text()
    assert "PEREZ_12345678" not in written
    assert activity.UNDECLARED in written


def test_a_frozen_build_still_names_its_own_frames():
    """The bug this allowlist exists for, and the one that mattered most: PyInstaller rewrites
    co_filename to an anonymised relative path when it packs a module (archive/writers.py,
    "without absolute path to the module"), so a frame in the bundle reads
    "firmauy_desktop/tasks.py" while __file__ points inside the bundle. Comparing absolute
    prefixes called every frame of the app foreign, in the one build that has no console for a
    traceback to go to.
    """
    assert activity._source_file("firmauy_desktop/tasks.py") == "firmauy_desktop/tasks.py"
    assert activity._source_file("/anywhere/src/firmauy_desktop/tasks.py") == \
        "firmauy_desktop/tasks.py"
    assert activity._source_file(r"C:\build\src\firmauy_desktop\tasks.py") == \
        "firmauy_desktop/tasks.py"


def test_a_frame_can_only_ever_say_what_this_module_already_knows():
    """A path that ends in a real source name is matched, and what gets written is the entry from
    the set rather than the traceback's string, so a forged filename buys no new text."""
    assert activity._source_file("/home/juana/firmauy_desktop/tasks.py") == \
        "firmauy_desktop/tasks.py"
    assert activity._source_file("/home/juana/contrato-divorcio.pdf") is None
    assert activity._source_file(str(Path(activity.__file__).parent / "contrato.pdf")) is None
    assert activity._source_file(None) is None


def test_the_source_files_are_the_files_that_are_there():
    """Declared rather than listed at import, because in a frozen build the .py files are inside
    the PYZ and not on disk to be walked. A module added and not named here would have its
    frames counted instead of shown, which is the quiet way a crash record stops being useful."""
    src = Path(__file__).resolve().parent.parent / "src"
    on_disk = {path.relative_to(src).as_posix() for path in src.rglob("*.py")}

    assert on_disk, "no source files found at all, which cannot be right"
    assert activity.SOURCE_FILES == on_disk


def test_recording_a_crash_never_opens_the_file_a_frame_names(qapp, tmp_path):
    """traceback.extract_tb looks source lines up as it goes: it opens whatever each frame's
    co_filename names and leaves the contents in linecache. With a document as that name it read
    the document, a moment before the frame was classified as foreign and thrown away.

    Nothing of it ever reached the file. But a module whose whole design is not to touch somebody
    else's text should not be opening their documents in order to decide it did not want them.
    """
    import linecache

    document = tmp_path / "contrato-divorcio.pdf"
    document.write_text("SECRETO-TITULAR-JUANA-PEREZ\n", encoding="utf-8")

    activity.configure(True)
    linecache.clearcache()
    try:
        exec(compile("raise RuntimeError('x')", str(document), "exec"))
    except RuntimeError as exc:
        activity.crash(exc)

    assert str(document) not in linecache.cache, "the record opened somebody's document"
    written = _text()
    assert "SECRETO" not in written and "contrato-divorcio" not in written
    assert "crash  RuntimeError" in written      # recorded, so this can fail


@pytest.mark.parametrize("line", [0, -1, "12", None, True])
def test_a_frame_without_a_real_line_number_is_counted_not_shown(line):
    """Zero is not a line: source lines are numbered from one. Nor is a string, nor a boolean,
    though Python calls that an integer. A frame carrying one is counted, like any other this
    record cannot place.

    Asserted on the pair rather than on the file, because a timestamp of 21:04 contains ":0" and
    the first version of this test failed on its own clock.
    """
    class Frame:
        f_code = type("Code", (), {"co_filename": "firmauy_desktop/tasks.py"})

    class Tb:
        tb_frame, tb_lineno, tb_next = Frame(), line, None

    class Fake(Exception):
        __traceback__ = Tb()

    named, elsewhere, truncated = activity._frames(Fake())
    assert named == []
    assert elsewhere == 1
    assert truncated is False


def test_a_line_number_beyond_this_package_is_not_written(qapp):
    """A code object declares its own line, and replace(co_firstlineno=12345678) put exactly that
    in the record: the file name was resolved against a closed set while the number beside it was
    taken as given."""
    activity.configure(True)
    forged = compile("raise RuntimeError('x')", "firmauy_desktop/tasks.py", "exec").replace(
        co_firstlineno=12345678)
    try:
        exec(forged)
    except RuntimeError as exc:
        activity.crash(exc)

    written = _text()
    assert "12345678" not in written
    assert "crash  RuntimeError" in written      # recorded, so this can fail


def test_no_file_in_this_package_reaches_the_bound():
    """One bound instead of a line count per file, so the bound has to stay true of all of them.
    It is generous on purpose: an exact map would fail constantly and be fixed by pasting back
    the number the test printed, which is a ritual rather than a check."""
    src = Path(__file__).resolve().parent.parent / "src"
    longest = max((len(path.read_text(encoding="utf-8").splitlines()), path.name)
                  for path in src.rglob("*.py"))

    assert longest[0] < activity.MAX_SOURCE_LINE, f"{longest[1]} has outgrown the bound"


def test_a_cyclic_traceback_cannot_hold_the_record_hostage():
    """__traceback__ is an attribute like any other and nothing stops it pointing at itself.
    Measured before this: a tb_next cycle held _frames forever, and tasks.py calls crash() before
    re-raising, so the operation being described would never have finished either.

    The rule here was never "must not raise". It is "must not stop the operation it is
    describing", and a loop breaks that harder than an exception, which at least propagates.
    """
    class Frame:
        f_code = type("Code", (), {"co_filename": "firmauy_desktop/tasks.py"})()

    class Tb:
        pass

    tb = Tb()
    tb.tb_frame, tb.tb_lineno, tb.tb_next = Frame(), 10, tb

    class Fake(Exception):
        __traceback__ = tb

    named, elsewhere, truncated = activity._frames(Fake())

    assert named == ["firmauy_desktop/tasks.py:10"]
    assert truncated is True


def test_a_traceback_longer_than_the_budget_stops_and_says_so():
    """The other half of the same bound: a chain with no cycle but no end in sight."""
    class Frame:
        f_code = type("Code", (), {"co_filename": "firmauy_desktop/tasks.py"})()

    class Tb:
        def __init__(self, nxt):
            self.tb_frame, self.tb_lineno, self.tb_next = Frame(), 1, nxt

    chain = None
    for _ in range(activity.MAX_FRAMES + 10):
        chain = Tb(chain)

    class Fake(Exception):
        __traceback__ = chain

    named, elsewhere, truncated = activity._frames(Fake())

    assert len(named) == activity.MAX_FRAMES
    assert truncated is True


def test_a_truncated_walk_says_so_without_counting_what_it_skipped(qapp):
    """A count would mean walking the rest of a chain this stopped walking on purpose."""
    class Frame:
        f_code = type("Code", (), {"co_filename": "firmauy_desktop/tasks.py"})()

    class Tb:
        pass

    tb = Tb()
    tb.tb_frame, tb.tb_lineno, tb.tb_next = Frame(), 10, tb

    class Fake(Exception):
        __traceback__ = tb

    activity.configure(True)
    activity.crash(Fake())

    written = _text()
    assert "traza truncada" in written
    assert "firmauy_desktop/tasks.py:10" in written


def test_a_failure_the_app_cannot_name_leaves_a_crash_behind(qapp):
    """The gap between the two rules this app already had, and it was invisible from either side.

    backend never raises, on purpose: a bug in the core must not take a screen down, so every
    call catches and returns a result. Task.run records a crash and re-raises, on purpose: an
    unanticipated failure is the one worth a traceback. Together they cancelled out. A genuine
    bug in firmauy became a Result, Task.run saw no exception, and somebody with the record
    switched on got a file with no trace of the very thing it exists for.

    So it is noted where the app decides it has run out of sentences, which is the same place
    that decides what to put on screen.
    """
    def boom():
        raise RuntimeError("impossible internal state")

    activity.configure(True)
    result = backend._call(boom)

    assert result.ok is False
    assert "no reconoce" in result.error                  # the person still gets a sentence
    written = _text()
    assert "crash  RuntimeError" in written
    assert "firmauy_desktop/backend.py:" in written       # which call broke


def test_a_failure_the_app_knows_how_to_name_is_not_a_crash(qapp):
    """A wrong PIN and an absent card are conditions, not bugs, and a record that logs a
    traceback for every one of them is a record nobody reads."""
    from firmauy.api import CardNotFoundError, IncorrectPinError

    activity.configure(True)
    for exc in (CardNotFoundError("no card"), IncorrectPinError("wrong", attempts_remaining=2)):
        backend._call(lambda exc=exc: (_ for _ in ()).throw(exc))

    assert "crash" not in _text()


def test_the_message_of_an_unrecognised_failure_stays_out_of_the_record(qapp):
    """It is on screen for the person to paste, and it is written by libraries underneath, so it
    can hold anything. The crash entry names the class and this app's own frames, nothing else.
    """
    def boom():
        raise RuntimeError(f"falló sobre {DOCUMENT} de {HOLDER}")

    activity.configure(True)
    result = backend._call(boom)

    assert DOCUMENT in result.error and HOLDER in result.error     # the screen keeps the detail
    written = _text()
    assert "crash  RuntimeError" in written
    assert "contrato-divorcio" not in written and "juana" not in written
    assert HOLDER not in written


def test_a_batch_failure_is_recorded_once_and_not_twice(qapp, monkeypatch, tmp_path):
    """The crash entry lives where the app decides it has no sentence, so asking that question
    twice answered it twice. The batch asked once for the row and once for the batch, and the
    same failure appeared in the file two times over, which reads as two things going wrong.
    """
    from firmauy.api import BatchSignError

    document = tmp_path / "a.pdf"
    document.write_bytes(b"%PDF-1.7\n")

    def fake(paths, **kw):
        error = BatchSignError("stopped", failed_index=0, completed=[], callback_error=None)
        raise error from RuntimeError("impossible internal state")

    monkeypatch.setattr(backend, "_api_sign_files", fake)
    activity.configure(True)
    result = backend.sign_batch([str(document)], pin_provider=lambda: PIN, native=True)

    assert result.ok is False
    assert _text().count("crash  RuntimeError") == 1


def test_a_photo_that_fails_for_no_known_reason_still_leaves_a_trace(qapp, monkeypatch):
    """The one path that drops a failure instead of turning it into a sentence.

    Reading the cardholder photo is allowed to fail quietly, because the biographic data is
    worth showing without it. That is right, and it meant a real bug in there was the one
    failure in this module that left nothing anywhere: no sentence, no kind, no crash.
    """
    from firmauy.api import IdentityReport

    def person(**kw):
        return IdentityReport(lastnames="PEREZ", given_names="PERSONA DE PRUEBA",
                              id_number="1.234.567-8")

    def broken_photo(**kw):
        raise RuntimeError("impossible internal state")

    monkeypatch.setattr(backend, "_api_fetch_identity", person)
    monkeypatch.setattr(backend, "_api_fetch_photo", broken_photo)
    activity.configure(True)
    result = backend.read_identity()

    assert result.ok is True                      # the screen still shows the cédula
    assert result.identity.photo is None
    written = _text()
    assert "crash  RuntimeError" in written
    assert "PEREZ" not in written and "1.234.567-8" not in written


def test_a_card_with_no_photo_is_not_a_crash(qapp, monkeypatch):
    """Plenty of cards have no photo to read, and a record that calls that a bug is a record
    that cries wolf on the ordinary case."""
    from firmauy.api import CardNotFoundError, IdentityReport

    monkeypatch.setattr(backend, "_api_fetch_identity",
                        lambda **kw: IdentityReport(lastnames="PEREZ",
                                                    given_names="PERSONA DE PRUEBA",
                                                    id_number="1.234.567-8"))
    monkeypatch.setattr(backend, "_api_fetch_photo",
                        lambda **kw: (_ for _ in ()).throw(CardNotFoundError("no photo")))
    activity.configure(True)
    result = backend.read_identity()

    assert result.ok is True
    assert "crash" not in _text()
