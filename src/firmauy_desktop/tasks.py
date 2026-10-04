# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Running backend work off the UI thread, and keeping the card to one caller at a time.

Every card and filesystem call blocks for seconds, and Qt forbids touching widgets from a
worker thread, so each screen hands its work to a ``TaskRunner``. The runner owns the thread
object (a `QThread` stored in a local is garbage collected mid-run), refuses to start a second
one on top of the first, drops the result of a run nobody is waiting for any more, and can be
waited on before the window closes, because destroying a running `QThread` aborts the process.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from PySide6.QtCore import QObject, QThread, Signal

from firmauy_desktop import activity


# Every task that has been started and may still be running. Letting Python collect a running
# QThread aborts the process, and the object that owns the task is routinely gone before the
# thread is: a runner emits its result the instant the callable returns, a beat before run()
# unwinds and Qt finishes the thread, and by then a dialog may have closed or a local gone out of
# scope. Parenting is not enough either, since the parent can be the thing that disappeared. This
# is the backstop, and it is swept on every start so nothing accumulates.
_ALIVE: "set[Task]" = set()


class Deadline:
    """One wall-clock budget, shared by everything that has to finish before the window goes.

    Closing the window waits on eight runners across five screens, and a budget that each of them
    starts fresh is eight budgets. Measured, with one parked thread in each and the shipped five
    seconds: forty seconds to close an app that looks idle. The number moved with the number of
    runners, which is the wrong thing for it to depend on.

    Passed down rather than recomputed, so the whole close spends one budget no matter how the
    screens are arranged. ``remaining()`` never goes below zero, and zero means QThread.wait
    returns at once with whether the thread had already finished.
    """

    __slots__ = ("_until",)

    def __init__(self, msec: int) -> None:
        self._until = time.monotonic() + msec / 1000

    def remaining(self) -> int:
        return max(0, round((self._until - time.monotonic()) * 1000))


def _deadline(budget: "int | Deadline") -> Deadline:
    """Accept either, so a caller with nothing to share still reads plainly."""
    return budget if isinstance(budget, Deadline) else Deadline(budget)


def _keep_alive(task: "Task") -> None:
    for finished in [t for t in _ALIVE if t.isFinished()]:
        _ALIVE.discard(finished)
    _ALIVE.add(task)


class Task(QThread):
    """Runs one backend callable off the UI thread and emits whatever it returned.

    Both signals carry the task itself. That is what lets the runner tell whose result just
    arrived without ``QObject.sender()``, which comes back None for a task that has already been
    waited on and would make an identity check pass by accident.

    Nothing is swallowed here. ``backend.py``'s contract is that it never raises: every function
    catches and returns a result object. If something does escape, it keeps escaping (PySide6
    prints the traceback, and pytest-qt turns it into a failed test), while the ``finally`` still
    reports that this task settled, so the runner can free the screen instead of leaving it stuck
    on "working...". Catching would bury a backend bug, and swallow KeyboardInterrupt with it.

    The ``except`` that does exist only writes the failure to the activity record and re-raises,
    so both properties hold at once. It earns its place on the packaged build: the spec sets
    ``console=False``, so the traceback PySide6 prints has nowhere to go on Windows or macOS, and
    an unanticipated crash was the one failure that left no trace anybody could send.
    """

    done = Signal(object, object)   # (task, result)
    settled = Signal(object)        # (task), always, even when the callable raised

    def __init__(self, fn: Callable[..., object], /, *args, **kwargs) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def _call(self) -> object:
        return self._fn(*self._args, **self._kwargs)

    def run(self) -> None:
        try:
            self.done.emit(self, self._call())
        except Exception as exc:      # not BaseException: KeyboardInterrupt is not a bug report
            activity.crash(exc)
            raise
        finally:
            self.settled.emit(self)


class ProgressTask(Task):
    """A Task whose callable takes a ``progress`` keyword it may call while it works.

    The callback wraps a Qt signal's ``emit``, so the callable reports progress without knowing
    anything about Qt or about which thread the listener is on: the delivery is queued to the
    receiver's thread like any other cross-thread signal. The task travels with every report for
    the same reason it travels with ``done``: without it, the reports of an abandoned run would
    keep painting the screen of the run that replaced it.
    """

    progress = Signal(object, object)   # (task, payload)

    def _call(self) -> object:
        return self._fn(*self._args,
                        progress=lambda payload: self.progress.emit(self, payload),
                        **self._kwargs)


class TaskRunner(QObject):
    """At most one task in flight per screen.

    Lives on the UI thread and is only ever driven from it, so it needs no locking of its own.
    """

    finished = Signal(object)   # the backend's result
    progress = Signal(object)   # only from run_with_progress
    crashed = Signal()          # the callable raised, so there is no result to deliver

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._task: Optional[Task] = None
        self._retired: list[Task] = []
        self._busy = False
        self._delivered = False

    @property
    def busy(self) -> bool:
        return self._busy

    def run(self, fn: Callable[..., object], /, *args, **kwargs) -> bool:
        """Start ``fn(*args, **kwargs)`` on a worker thread. False when one is already running."""
        return self._start(Task(fn, *args, **kwargs))

    def run_with_progress(self, fn: Callable[..., object], /, *args, **kwargs) -> bool:
        """Same, for a callable that accepts a ``progress`` keyword. False when already running."""
        return self._start(ProgressTask(fn, *args, **kwargs))

    def abandon(self) -> None:
        """Stop waiting for the task in flight and free the runner for the next one.

        The thread is not stopped, because a `QThread` blocked in a card read or a revocation
        fetch cannot be killed. It is retired to a list that holds it alive until it ends, since
        letting Python collect a running `QThread` aborts the process. Whatever it eventually
        produces is dropped, because it is no longer this runner's current task.
        """
        if self._task is None:
            return
        self._retired.append(self._task)
        self._task = None
        self._busy = False

    def shutdown(self, budget: "int | Deadline" = 5000) -> "list[Task]":
        """Wait for everything this runner started, inside one budget. Before the window closes.

        The budget is the whole wait, not each task's turn at it: a turn each reads the same
        until something is abandoned, and abandoning is a button. "Dejar de esperar" retires a
        revocation check that is not answering and frees the screen to try again, so three
        unanswered lookups leave three threads parked here. Measured with a 300 ms budget and a
        turn each: 900 ms.

        A ``Deadline`` shares one budget with the other runners closing alongside this one, which
        is the version that holds for the window rather than for a screen. An int is the same
        thing for a caller that has nothing to share it with.

        A task still running when the budget runs out is left running, and that is not the end of
        the story: destroying a live QThread aborts the process, so whoever owns the close has to
        decide what happens next. ``_ALIVE`` keeps it from being collected while the app runs.

        Returns the tasks that outlived the budget, so the caller can tell "everything finished"
        from "time ran out", which are the same shape and want different endings.
        """
        deadline = _deadline(budget)
        waited = [task for task in [self._task, *self._retired] if task is not None]
        for task in waited:
            task.wait(deadline.remaining())
        self._task = None
        self._retired.clear()
        self._busy = False
        return [task for task in waited if task.isRunning()]

    def _start(self, task: Task) -> bool:
        if self._busy:
            return False
        # The outgoing task may still be winding down (busy is cleared when its result arrives,
        # a moment before its thread actually ends), and dropping the last reference to a live
        # QThread aborts the process. Hold it until it really is finished.
        self._retired = [t for t in self._retired if t.isRunning()]
        if self._task is not None and self._task.isRunning():
            self._retired.append(self._task)

        self._task = task
        self._busy = True
        self._delivered = False
        # Bound methods of this QObject, which lives on the UI thread, so Qt delivers both queued.
        task.done.connect(self._on_done)
        task.settled.connect(self._on_settled)
        if isinstance(task, ProgressTask):
            task.progress.connect(self._on_progress)
        _keep_alive(task)
        task.start()
        return True

    def _on_progress(self, task: Task, payload: object) -> None:
        if task is not self._task:
            return                      # an abandoned or superseded run: nobody wants its reports
        self.progress.emit(payload)

    def _on_done(self, task: Task, result: object) -> None:
        if task is not self._task:
            return                      # an abandoned or superseded run: nobody wants this
        self._delivered = True
        self._busy = False
        self.finished.emit(result)

    def _on_settled(self, task: Task) -> None:
        if task is not self._task or self._delivered:
            return
        # The task ended without producing a result, so the callable raised. PySide6 has already
        # printed the traceback; all that is left is to free the runner and let the screen say
        # something instead of staying stuck on "working...".
        self._busy = False
        self.crashed.emit()


class CardLock(QObject):
    """Serialises every operation that talks to the card, across screens.

    firmauy cannot read the cardholder's data while a signing session is open on the same card:
    both go through pcscd and conflict. Today the two flows are separate enough that colliding
    them takes effort, but once moving between screens is one click it becomes a one-click bug.

    Only ever touched from the UI thread (acquire before starting a task, release when it
    settles), so it is a plain flag rather than a threading primitive.
    """

    changed = Signal(bool)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._owner = ""

    @property
    def busy(self) -> bool:
        return bool(self._owner)

    def owner(self) -> str:
        """Who holds the card right now, for a message like "la cédula está firmando"."""
        return self._owner

    def acquire(self, owner: str) -> bool:
        if self._owner:
            return False
        self._owner = owner
        self.changed.emit(True)
        return True

    def release(self, owner: str) -> None:
        if self._owner != owner:
            return              # a late release from an abandoned run must not free somebody else
        self._owner = ""
        self.changed.emit(False)
