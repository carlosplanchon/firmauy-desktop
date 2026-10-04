# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""An opt-in record of what the app did, for reporting a problem.

It exists for one situation. When something fails in a way nobody anticipated, the only trace
today is what PySide6 prints to stderr, and the packaged build sets ``console=False``, so on
Windows and macOS that goes nowhere anybody can retrieve. Somebody reporting a problem has
nothing to send.

**It is not a history of what you signed.** A file on disk is the most dangerous thing that can
be added to this app, because the app's whole posture runs the other way: SECURITY.md names "a
log" among the places the PIN must never reach, and settings.py explains why there is no
recent-files list, since it would put the names of the holder's documents somewhere that
outlives the uninstall. So this records the *shape* of what happened and never the subject:
which kind of signature, which backend, how many files, which class of error.

The rule is about where a value came from, not about what it looks like, and that is worth
stating because the two answers differ. How many files were signed is exactly the kind of number
this exists to keep and a cédula is exactly the kind it must never see, though both are numbers.
``backend.py`` belongs in a crash and ``contrato-divorcio.pdf`` does not, though both are file
names. What decides it is whose the value is: this program's, or the person's.

Nothing here rests on discipline. Three closed sets decide what can be written: the event has to
be one of :data:`EVENTS`, each field one of :data:`VOCABULARY`, and each value has to belong to
the domain of that particular field. Anything else is replaced, name and all. A crash does not
even reach that: it records the class of the failure and the line, never the exception's message,
since that text is written by other libraries and can hold anything.

Values are never filtered by pattern looking for what seems sensitive: a check that guesses
reads as a defence while letting "contrato.pdf" and "1.234.567-8" straight through. The posture
is the one :class:`~firmauy_desktop.backend.DoctorCheck` already takes with its ``sensitive``
flag defaulting to True: when in doubt, hide it.

Off by default, and off means nothing at all: no handler, no file, not even an empty one.
"""

from __future__ import annotations

import builtins
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QStandardPaths

# Small on purpose. This is meant to be attached to a bug report, not kept as an audit trail, and
# a file somebody has to be talked through truncating is a file that grows forever.
MAX_BYTES = 256 * 1024
BACKUPS = 1

# What is written in place of anything this record is not allowed to say.
REDACTED = "[redactado]"

# And what a field nobody declared becomes: both halves of the pair, so no byte of it is the
# caller's. Python does not require a keyword to look like an identifier, and
# ``event("firma", **{"contrato-divorcio.pdf": 1})`` is a legal call.
UNDECLARED = f"campo_no_declarado={REDACTED}"

# The whole language this record is written in: which things can be said, and what each of them
# is allowed to say. Closing the field names was half of it, since a cédula, a surname and a file
# name are all a single token and any of them fitted in a field that was merely *named* correctly.
#
# Every event this app records, and both barriers apply to it. A test reads the call sites, which
# is what forces the vocabulary to be visible in the source and catches a line written here before
# it can run. The check in `event` catches a call that test's pattern never saw, an aliased import
# among them, and it is not too late for coming after the f-string is built: that the string
# existed for an instant is nothing, that it reaches the file is everything.
EVENTS = frozenset({
    "registro iniciado",
    "firma", "firma cancelada", "firma falló", "firma lista",
    "lote", "lote listo", "lote se detuvo",
    "verificación lista", "verificación falló",
    "lote a verificar", "lote verificado",
    "diagnóstico", "diagnóstico falló",
    "icono no encontrado",
    # The window gave up waiting on a thread that cannot be interrupted and took the
    # exit itself, rather than letting Qt abort on the way out.
    "cierre forzado",
})

# What backend._kind can answer. Declared rather than imported, since backend imports this module,
# and held against that function by a test so a kind added there cannot go quietly redacted here.
ERROR_KINDS = frozenset({
    "access_control", "callback_failed", "cancelled", "card", "card_other", "cert",
    "needs_original", "not_found", "other", "output_committed", "output_exists", "pin",
    "pin_format", "pin_last_try", "pin_locked", "reader", "stamp", "token",
    "tsa_destination_refused", "tsa_failed", "verify_failed",
})

# Fields whose value must be one of a handful of words. This is the layer that turns "a closed
# vocabulary" from a description of the call sites into a property of the record.
# The icon set, by name. Declared for the same reason as ERROR_KINDS: ui.icons imports this
# module, so it cannot be imported back, and a test holds this against the files on disk.
#
# A domain even for names that are files in the package and never anybody's data: that is true
# of the seventeen, and not something the code enforces without this set. icons.pixmap takes a
# string, and a caller passing one that came from somewhere else would put it in the record. An
# argument about how the callers behave is exactly what this whole module refuses to rest on.
ICON_NAMES = frozenset({
    "activity", "arrow-right", "check", "check-on-accent-dark", "check-on-accent-light",
    "chevron-down", "chevron-right", "circle", "cross", "dot", "gear", "id-card", "pen",
    "shield-check", "sliders", "upload", "warning",
})

_ENUM = {
    "name": ICON_NAMES,
    "backend": frozenset({"native", "pkcs11"}),
    "kind": frozenset({"pades", "xades", "cades"}),
    "sign_as": frozenset({"auto", "pdf", "xml", "cades"}),
    "indication": frozenset({"VALID", "INVALID", "INDETERMINATE"}),
    "error_kind": ERROR_KINDS,
}
_FLAG = frozenset({"ok", "revocation", "stamped", "verified", "verify"})
_COUNT = frozenset({"fallos", "firmados", "firmas", "n", "total"})

VOCABULARY = frozenset(_ENUM) | _FLAG | _COUNT

# This program's own source files, by the path a traceback carries. A frame is named only when it
# matches one of these, and what gets written is the entry from this set rather than anything out
# of the traceback, so even a code object compiled with a name ending in "tasks.py" can only make
# this record say "firmauy_desktop/tasks.py".
#
# Matched on the tail rather than against an absolute prefix, and that is not only about spoofing.
# PyInstaller rewrites co_filename to an anonymised relative path when it packs a module into the
# PYZ (archive/writers.py: "without absolute path to the module"), so in a frozen build the frame
# says "firmauy_desktop/tasks.py" while __file__ points inside the bundle. Comparing prefixes
# counted every frame of the app as foreign, in the one build where this record exists at all,
# because that build has no console for a traceback to go to.
# The largest line number a frame of this program can honestly carry. A code object declares its
# own, and `compile(...).replace(co_firstlineno=12345678)` put exactly that in the record, so the
# file name was resolved against a closed set while the number beside it was not.
#
# One bound rather than a line count per file, which would be tighter and is not worth it: a
# source file changes many times between releases, so an exact map would fail constantly and
# be fixed by pasting back the number the test just printed.
# A check that has to be performed without thinking is the kind of ritual this module replaced.
# Generous on purpose, so every file has room to grow and a forgery is still refused. How close
# the longest one comes is measured by test_no_file_in_this_package_reaches_the_bound rather than
# written here, where a figure went stale as the files grew.
MAX_SOURCE_LINE = 5000

# How far this record will walk a traceback. A real one is a finite chain, but __traceback__ is an
# attribute like any other and nothing stops it pointing at itself: measured, a tb_next cycle held
# _frames forever. The rule this module works to is not that it must never raise, it is that it
# must never keep the operation it is describing from finishing, and a loop breaks that harder
# than an exception does, since an exception at least propagates.
#
# Generous, because truncating a real crash costs the deep end of it, which is where it broke.
# Python's own recursion limit puts a real traceback well under this except for a RecursionError,
# and that one repeats the same frames anyway.
MAX_FRAMES = 256

SOURCE_FILES = frozenset({
    "firmauy_desktop/__init__.py", "firmauy_desktop/activity.py", "firmauy_desktop/app.py",
    "firmauy_desktop/backend.py", "firmauy_desktop/dialogs.py", "firmauy_desktop/labels.py",
    "firmauy_desktop/main_window.py", "firmauy_desktop/pinflow.py",
    "firmauy_desktop/settings.py", "firmauy_desktop/tasks.py", "firmauy_desktop/ui/__init__.py",
    "firmauy_desktop/ui/components.py", "firmauy_desktop/ui/icons.py",
    "firmauy_desktop/ui/theming.py", "firmauy_desktop/ui/tokens.py",
    "firmauy_desktop/views/__init__.py", "firmauy_desktop/views/advanced_view.py",
    "firmauy_desktop/views/doctor_view.py", "firmauy_desktop/views/identity_view.py",
    "firmauy_desktop/views/settings_dialog.py", "firmauy_desktop/views/sign_view.py",
    "firmauy_desktop/views/verify_view.py", "firmauy_desktop/widgets.py"
})

# Exception classes this record is allowed to name, taken from the interpreter rather than from
# the exception: `type("PEREZ_12345678", (Exception,), {})` has a __name__ like anything else.
# FIRMAUY_ERRORS is declared for the reason ERROR_KINDS is, and one reaching here at all means
# backend broke its own promise never to raise, which is the crash most worth naming precisely.
FIRMAUY_ERRORS = frozenset({
    "BatchSignCancelled", "BatchSignError", "CardNotFoundError", "CertificateError",
    "CertificateNotFoundError", "CertificateNotValidError", "DetachedOriginalRequiredError",
    "FirmaUYError", "IncorrectPinError", "OutputAccessControlError", "OutputCommittedError",
    "OutputExistsError", "PinError", "PinFormatError", "PinLastTryError", "PinLockedError",
    "PostSignVerificationError", "ReaderNotFoundError", "SigningKeyNotFoundError",
    "TimestampDestinationRefusedError", "TimestampError", "TokenNotFoundError",
})
EXCEPTIONS = frozenset(
    name for name, obj in vars(builtins).items()
    if isinstance(obj, type) and issubclass(obj, BaseException)
) | FIRMAUY_ERRORS

_LOGGER = logging.getLogger("firmauy_desktop.activity")
_HANDLER: Optional[RotatingFileHandler] = None


def log_path() -> Path:
    """Where the record is written.

    ``StateLocation`` is the standard place for exactly this and Qt resolves it per platform
    (``~/.local/state/...`` here, the right equivalent on Windows and macOS). It arrived in Qt
    6.7, which is this project's PySide6 floor, so it needs no fallback.

    A function rather than a constant because it is what the tests replace. The autouse fixture
    in conftest points it at a tmp_path: the settings isolation next to it only redirects
    QSettings, so without that the suite would write into the developer's real home on every run.
    """
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.StateLocation)
    return Path(base) / "actividad.log"


def is_on() -> bool:
    """Whether anything is being recorded right now.

    The screens ask this before telling somebody where an unexpected failure went. Telling a
    person to switch on a record they already have on is the kind of advice that teaches them to
    stop reading the messages.

    The handler rather than the setting, because they can disagree: the setting is what Ajustes
    will apply, and the record is what is open at this instant. A read-only state directory
    leaves the box ticked and nothing writing, and this has to say no in that case.
    """
    return _HANDLER is not None


def written_files() -> list[Path]:
    """Every file the record has produced, including the rotated one. What Ajustes deletes."""
    main = log_path()
    return [path for path in [main, *(main.parent.glob(main.name + ".*"))] if path.is_file()]


def _value(key: str, value: object) -> str:
    """One field's value, checked against what that particular field is allowed to hold.

    Per field, not per type, and that is the point: "1.234.567-8", "PEREZ" and "contrato.pdf" are
    each a single token, so a rule about shape let all three through a field whose name happened
    to be allowed. A backend is one of two words, a count is a whole number that is not negative,
    a flag is a boolean. Anything else is replaced.

    Replaced rather than dropped or raised. Raising would end an operation over a log entry, and
    dropping would leave no trace that a field had been there at all, which is the version of
    this that hides its own mistakes.

    ``type(value) is`` rather than ``isinstance``, which is the one place in this app where that
    is the right test. A subclass gets to define ``__hash__`` and ``__str__``, so ``value in
    allowed`` and ``str(value)`` are both calls into somebody else's code, and either can raise
    from inside the logger. Nothing legitimate reaches here as a subclass: these values are
    literals out of a fixed vocabulary. Exactness is free, and it makes "this cannot raise" a
    property rather than an expectation.
    """
    if key in _FLAG:
        return str(value) if type(value) is bool else REDACTED
    if key in _COUNT:
        return str(value) if type(value) is int and value >= 0 else REDACTED
    allowed = _ENUM.get(key)
    if allowed is not None:
        return value if type(value) is str and value in allowed else REDACTED
    return REDACTED                         # a field nobody declared says nothing at all


def configure(enabled: bool) -> None:
    """Turn the record on or off. Safe to call repeatedly, and with the same value.

    Off removes the handler, so nothing is opened, created or written. Turning it off does not
    delete what is already there: somebody who reproduced a problem and then switched the
    setting would lose the very thing they were about to send. Ajustes offers a button for that
    instead, where deleting is the thing being asked for.
    """
    global _HANDLER

    if enabled == (_HANDLER is not None):
        return

    if not enabled:
        _LOGGER.removeHandler(_HANDLER)
        _HANDLER.close()
        _HANDLER = None
        return

    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS,
                                      encoding="utf-8")
    except OSError:
        # A read-only or missing state directory is not a reason to refuse to start. The app
        # runs without the record, which is what it did before this existed.
        return

    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s",
                                           datefmt="%Y-%m-%d %H:%M:%S"))
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.INFO)
    # Nothing propagates to the root logger, so a disabled record cannot reach stderr through
    # logging's last-resort handler either.
    _LOGGER.propagate = False
    _HANDLER = handler
    event("registro iniciado")


def clear() -> int:
    """Delete what the record has written, and carry on recording if it was on.

    This lives here rather than in Ajustes because the handler does, and unlinking a file
    somebody else has open does not mean what it looks like it means. Measured on Linux: with
    the handler still open, the delete succeeded, the name left the directory, and the next four
    entries, a crash among them, went on being written into the unnamed inode the descriptor
    still pointed at. The button reported success, ``written_files()`` returned nothing, and the
    person who deleted the record so they could reproduce a problem cleanly had no file to send.
    On Windows the same call tends to fail outright with the file open, so the one bug is two.

    So the handler is closed first, which is what makes the delete mean it on both platforms,
    and reopened afterwards. Deleting is about what was recorded, not about whether to record:
    somebody who cleared the file and kept the setting on expects the next thing that happens to
    be in there. Reopening writes "registro iniciado", so the file exists again immediately and
    there is always something to attach.

    Reopening happens even if a delete fails, which is why it is in a ``finally``. The failure
    a person sees is a message about one file, not a record that quietly stopped working with
    the setting still switched on.

    Returns how many files it removed. Raises OSError if one refused to go, unlike everything
    else in this module: this is the operation the user asked for rather than a note taken
    alongside one, so it owes them the reason it did not happen.
    """
    was_on = _HANDLER is not None
    configure(False)
    removed = 0
    try:
        for path in written_files():
            try:
                path.unlink()
            except FileNotFoundError:
                continue        # rotation, or a second window: gone is the outcome asked for
            removed += 1
    finally:
        if was_on:
            configure(True)
    return removed


def event(what: str, /, **fields: object) -> None:
    """One thing that happened, plus scalar fields from the closed vocabulary.

    Positional-only, so a field may be called anything at all. It was not, and the first caller
    wanting to record a ``name=`` collided with the parameter.

    ``event("firma", sign_as="auto", backend="native", verify=True)``. The name, the fields and
    the values are each held to what this record may say, so a call carrying anything else writes
    a marker rather than the thing. ``batch`` was in this example and is not a field at all.
    """
    if _HANDLER is None:
        return
    # Checked here as well as by the test that reads the call sites, and the earlier note that a
    # run-time check "comes too late" had the goal wrong: the point is not to catch the mistake,
    # it is that nothing arbitrary reaches the file. The test covers a line written in this
    # package, this covers a call the test's pattern never saw, an aliased import among them.
    name = what if type(what) is str and what in EVENTS else REDACTED
    # The key is caller text as much as the value is. Checking one and copying the other
    # destroyed half the pair and wrote the rest down.
    # `type(key) is str` for the reason the values have it: a subclass gets to define __hash__
    # and __eq__, so one can compare equal to "backend" while its own text says something else,
    # and the f-string writes the text. Measured: it put "PEREZ_12345678=native" in the file.
    tail = " ".join(f"{key}={_value(key, value)}"
                    if type(key) is str and key in VOCABULARY else UNDECLARED
                    for key, value in fields.items())
    _LOGGER.info("%s%s", name, f"  {tail}" if tail else "")


def crash(exc: BaseException) -> None:
    """An exception nobody anticipated: what it was, where it happened, and nothing else.

    The message is deliberately absent, and a filter over it is not an answer. Measured, one
    that looks for paths is weaker than any promise built on it: "falló contrato-divorcio.pdf de
    JUANA PEREZ" survives untouched and a path with a space in it leaves "de divorcio.pdf"
    behind. The deciding argument is not even that weakness: those strings are not this app's.
    They are written by pyHanko, cryptography and Qt, they can hold anything, and no filter over
    somebody else's text can be the basis of a guarantee.

    What is left is what a report actually needs: the class of failure and the line it came from.
    ``errno`` is the one property allowed through, because it is an integer and it is the
    difference between a file that was missing and one that could not be read.

    Where it happened is a file out of :data:`SOURCE_FILES` and a line inside this package's
    bounds, both resolved by :func:`_frames`, which reads the traceback without opening anything.
    """
    if _HANDLER is None:
        return
    named, elsewhere, truncated = _frames(exc)
    where = "".join(f"\n  {frame}" for frame in named)
    if elsewhere:
        where += f"\n  +{elsewhere} fuera de la app"
    # A fixed phrase, not a count: knowing how many were left would mean walking the rest of a
    # chain this stopped walking on purpose.
    if truncated:
        where += "\n  +traza truncada"
    number = _errno(exc)
    _LOGGER.error("crash  %s%s%s", _exception_name(exc),
                  f" errno={number}" if number is not None else "", where)


def _exception_name(exc: BaseException) -> str:
    """The class, when this record is allowed to name it, and "Exception" when it is not."""
    try:
        name = type(exc).__name__
    except BaseException:
        return "Exception"
    return name if type(name) is str and name in EXCEPTIONS else "Exception"


def _errno(exc: BaseException) -> Optional[int]:
    """The number an OSError carries, read off OSError's own descriptor.

    ``getattr(exc, "errno")`` runs whatever the class put there, and a property that raises would
    have taken this whole function with it. That matters more here than anywhere else in the
    module: tasks.py records a crash and then re-raises, so an exception escaping from in here
    would replace the one it was trying to write down, losing the bug and the record together.
    """
    try:
        number = OSError.errno.__get__(exc, type(exc)) if isinstance(exc, OSError) else None
    except BaseException:
        return None
    return number if type(number) is int else None


def _frames(exc: BaseException) -> tuple[list, int, bool]:
    """The frames in this program's own source, how many were somewhere else, and whether the
    walk stopped early.

    Every part of what gets written comes from this module: the file is the entry matched out of
    :data:`SOURCE_FILES`, never the traceback's own string, and the line is a plain integer. The
    function name is gone with the rest, because it is code-object metadata like the file name
    was, and ``firmauy_desktop/tasks.py:87`` is enough to find a crash again.

    Walked by hand rather than through ``traceback.extract_tb``, which looks source lines up as
    it goes: it opens whatever each frame's ``co_filename`` names and leaves the contents in
    ``linecache``. Measured, with a document as that name, it read the document. Nothing of it
    ever reached the file, since the frame was classified as foreign a moment later, but a module
    whose whole design is not to touch somebody's text should not be opening their documents to
    decide it did not want them.
    """
    named, elsewhere, truncated = [], 0, False
    try:
        current, seen = exc.__traceback__, set()
        for _ in range(MAX_FRAMES):
            if current is None:
                break
            # By identity, and every link is alive for as long as the exception holds the chain,
            # so an id cannot be reused underneath this walk.
            if id(current) in seen:
                truncated = True
                break
            seen.add(id(current))
            entry = _source_file(current.tb_frame.f_code.co_filename)
            line = current.tb_lineno
            # Numbered from one, and no larger than anything in this package can be.
            if entry is None or type(line) is not int or not 1 <= line <= MAX_SOURCE_LINE:
                elsewhere += 1
            else:
                named.append(f"{entry}:{line}")
            current = current.tb_next
        else:
            truncated = current is not None
    except BaseException:
        return [], 0, False
    return named, elsewhere, truncated


def _source_file(filename: object) -> Optional[str]:
    """Which of this program's files a frame is in, by its own name for it, or None."""
    if type(filename) is not str:
        return None
    tail = filename.replace("\\", "/")
    for entry in SOURCE_FILES:
        if tail == entry or tail.endswith("/" + entry):
            return entry
    return None
