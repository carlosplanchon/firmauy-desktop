# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the worker plumbing. No widgets and no card: the callables are plain functions."""

from __future__ import annotations

import threading

import pytest

from firmauy_desktop.tasks import CardLock, TaskRunner


def _blocking(event: threading.Event, value: str):
    """A callable that parks until the test releases it, then returns a recognisable value."""
    def work():
        event.wait(5)
        return value
    return work


def test_run_delivers_the_result_on_the_calling_thread(qtbot):
    runner = TaskRunner()
    seen = []
    runner.finished.connect(lambda r: seen.append((r, threading.current_thread())))

    with qtbot.waitSignal(runner.finished, timeout=5000):
        assert runner.run(lambda a, b: a + b, 2, b=3) is True

    result, thread = seen[0]
    assert result == 5
    assert thread is threading.main_thread()
    assert runner.busy is False


def test_run_refuses_a_second_task_while_one_is_in_flight(qtbot):
    release = threading.Event()
    runner = TaskRunner()

    with qtbot.waitSignal(runner.finished, timeout=5000) as blocker:
        assert runner.run(_blocking(release, "primero")) is True
        assert runner.busy is True
        assert runner.run(lambda: "segundo") is False    # refused, not queued
        release.set()

    assert blocker.args == ["primero"]


def test_abandon_drops_the_result_and_frees_the_runner(qtbot):
    """Regression too: the identity guard used to read QObject.sender(), which comes back None
    for a task that has already been waited on. With the runner's own task also None after
    shutdown, `None is not None` was False, the guard failed open, and the abandoned result was
    delivered on top of the real one. Both signals now carry the task itself.
    """
    release = threading.Event()
    runner = TaskRunner()
    seen = []
    runner.finished.connect(seen.append)

    runner.run(_blocking(release, "viejo"))
    runner.abandon()
    assert runner.busy is False                          # free for the next one right away

    with qtbot.waitSignal(runner.finished, timeout=5000):
        assert runner.run(lambda: "nuevo") is True

    release.set()
    runner.shutdown()
    qtbot.wait(50)                                       # let anything queued be delivered
    assert seen == ["nuevo"]                             # the abandoned run delivered nothing


@pytest.mark.qt_no_exception_capture
def test_a_raising_callable_reports_crashed_instead_of_hanging(qtbot):
    """The backend's contract is to never raise, but a bug there must not wedge the screen.

    The marker is required: pytest-qt turns an exception escaping a virtual method into a test
    failure, and letting one escape QThread.run is exactly what is under test here.
    """
    runner = TaskRunner()
    finished = []
    runner.finished.connect(finished.append)

    def boom():
        raise RuntimeError("simulated backend bug")

    with qtbot.waitSignal(runner.crashed, timeout=5000):
        runner.run(boom)

    assert finished == []
    assert runner.busy is False                          # the screen can try again

    # Wait for the thread to actually end. `crashed` comes from the finally, so the exception is
    # still on its way out of run() at this point, and letting the test return first lands it in
    # whichever test runs next, where this marker no longer suppresses it. That shows up as a
    # 1-in-40 failure somewhere unrelated, which is a miserable thing to chase.
    runner.shutdown()


def test_run_with_progress_forwards_the_callback(qtbot):
    runner = TaskRunner()
    steps = []
    runner.progress.connect(steps.append)

    def work(n, *, progress):
        for i in range(n):
            progress(f"paso {i}")
        return "listo"

    with qtbot.waitSignal(runner.finished, timeout=5000) as blocker:
        runner.run_with_progress(work, 3)

    assert blocker.args == ["listo"]
    assert steps == ["paso 0", "paso 1", "paso 2"]


def test_a_superseded_task_cannot_report_a_crash(qtbot):
    """A result arrives, the screen starts another run, and only then does the first thread
    actually end. That late `settled` must not be read as the second run crashing."""
    runner = TaskRunner()
    crashed = []
    runner.crashed.connect(lambda: crashed.append(True))

    with qtbot.waitSignal(runner.finished, timeout=5000):
        runner.run(lambda: "primero")
    with qtbot.waitSignal(runner.finished, timeout=5000):
        runner.run(lambda: "segundo")

    runner.shutdown()
    qtbot.wait(50)
    assert crashed == []


def test_shutdown_waits_for_the_task(qtbot):
    release = threading.Event()
    runner = TaskRunner()
    runner.run(_blocking(release, "algo"))
    release.set()
    runner.shutdown()
    assert runner.busy is False


def test_card_lock_admits_one_owner():
    lock = CardLock()
    changes = []
    lock.changed.connect(changes.append)

    assert lock.acquire("firmar") is True
    assert lock.busy is True
    assert lock.owner() == "firmar"
    assert lock.acquire("mi cédula") is False            # the card is taken

    lock.release("mi cédula")                            # a late release from the loser frees nothing
    assert lock.busy is True

    lock.release("firmar")
    assert lock.busy is False
    assert changes == [True, False]


def test_a_runner_that_goes_away_does_not_take_a_live_thread_with_it(qtbot):
    """The crash this guards against: letting Python collect a running QThread aborts the
    process, and a runner is routinely a local that goes out of scope the instant its result
    arrives, a beat before run() unwinds and Qt finishes the thread. Parenting does not help
    when the parent is the thing that went away."""
    import gc

    from firmauy_desktop import tasks

    release = threading.Event()

    def start_and_drop():
        runner = TaskRunner()                            # no parent, and about to go out of scope
        runner.run(_blocking(release, "algo"))

    start_and_drop()
    gc.collect()                                         # would have destroyed a live QThread

    assert any(not t.isFinished() for t in tasks._ALIVE)  # something is holding it
    release.set()
    qtbot.waitUntil(lambda: all(t.isFinished() for t in tasks._ALIVE), timeout=5000)


def test_finished_tasks_do_not_pile_up(qtbot):
    """The registry is swept on every start, so a long session does not accumulate threads."""
    from firmauy_desktop import tasks

    runner = TaskRunner()
    for _ in range(6):
        with qtbot.waitSignal(runner.finished, timeout=5000):
            runner.run(lambda: "listo")
    runner.shutdown()

    with qtbot.waitSignal(runner.finished, timeout=5000):
        runner.run(lambda: "otra")                       # this start sweeps the six before it
    runner.shutdown()

    assert len([t for t in tasks._ALIVE if t.isFinished()]) <= 1


def test_shutdown_spends_one_budget_and_not_one_per_task(qtbot):
    """Closing the window must not take five seconds per parked thread.

    "Dejar de esperar" is a button, so parked threads accumulate on purpose: a revocation check
    that is not answering gets abandoned and the person tries again. Each attempt retires a
    thread that is still blocked in the network call. Measured with the old per-task wait, a
    300 ms shutdown with three of them took 900 ms, and MainWindow closes five screens in turn.

    The bound is generous because a timing assertion on a loaded CI runner should fail for the
    behaviour, not for the weather. Three times the budget was the old, correct answer, so
    anything under twice it distinguishes them.
    """
    import time

    release = threading.Event()
    runner = TaskRunner()
    parked = []
    for index in range(3):
        runner.run(_blocking(release, str(index)))
        parked.append(runner._task)
        runner.abandon()

    start = time.monotonic()
    runner.shutdown(300)
    spent = (time.monotonic() - start) * 1000

    assert spent < 600, f"esperó {spent:.0f} ms, o sea por tarea y no en total"

    release.set()                       # let the threads end before the test drops them
    for task in parked:
        task.wait(5000)


def test_shutdown_still_waits_for_work_that_finishes_inside_the_budget(qtbot):
    """The budget bounds the wait, it does not skip it. A signature in flight when somebody
    clicks the close button still gets to finish, which is the whole reason this exists."""
    release = threading.Event()
    runner = TaskRunner()
    runner.run(_blocking(release, "listo"))
    task = runner._task

    release.set()
    runner.shutdown(5000)

    assert task.isFinished() is True


def test_an_abandoned_runs_progress_stops_arriving(qtbot):
    """abandon() frees the runner, and the abandoned run's reports go with its result: a
    stopped batch must not keep painting the rows of the run that replaced it."""
    gate = threading.Event()
    runner = TaskRunner()
    steps = []
    runner.progress.connect(steps.append)

    def work(*, progress):
        gate.wait(5)
        progress("tarde")
        return "listo"

    runner.run_with_progress(work)
    runner.abandon()
    gate.set()
    runner.shutdown(5000)
    qtbot.wait(50)                      # let any queued delivery land, if one were coming

    assert steps == []
