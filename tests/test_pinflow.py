# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the PIN handshake.

CONTRIBUTING declares two invariants about the PIN: it is asked for last, through a
pin_provider, and it is not kept once handed over. This is where they are checked.

Every test drives ``provider()`` from a worker thread, which is where firmauy calls it. Calling
it from the UI thread deadlocks by design, because ``requested`` is delivered queued.
"""

from __future__ import annotations

import threading

import pytest

from firmauy_desktop.backend import PinCancelled
from firmauy_desktop.pinflow import PinHandshake


def _ask_from_a_worker(handshake: PinHandshake) -> dict:
    """Call provider() off the UI thread the way firmauy does, and record what came back."""
    outcome: dict = {}

    def work():
        try:
            outcome["pin"] = handshake.provider()
        except PinCancelled:
            outcome["cancelled"] = True

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    outcome["thread"] = thread
    return outcome


def test_the_pin_travels_from_the_prompt_to_the_worker(qtbot):
    handshake = PinHandshake()

    with qtbot.waitSignal(handshake.requested, timeout=5000):
        outcome = _ask_from_a_worker(handshake)          # the request reaches the UI thread

    handshake.provide("1234")
    outcome["thread"].join(5)
    assert outcome["pin"] == "1234"


def test_the_pin_is_not_kept_after_it_is_handed_over(qtbot):
    handshake = PinHandshake()
    with qtbot.waitSignal(handshake.requested, timeout=5000):
        outcome = _ask_from_a_worker(handshake)

    handshake.provide("1234")
    outcome["thread"].join(5)

    assert outcome["pin"] == "1234"
    assert handshake._pin is None                        # nothing left on the object


@pytest.mark.parametrize("answer", [None, ""])
def test_dismissing_or_leaving_it_empty_cancels(qtbot, answer):
    handshake = PinHandshake()
    with qtbot.waitSignal(handshake.requested, timeout=5000):
        outcome = _ask_from_a_worker(handshake)

    handshake.provide(answer)
    outcome["thread"].join(5)

    assert outcome.get("cancelled") is True
    assert "pin" not in outcome


def test_the_timeout_cancels_rather_than_parking_forever(qtbot):
    """A prompt that never answers must not hold the card session open indefinitely."""
    handshake = PinHandshake(timeout_seconds=0.2)
    outcome = _ask_from_a_worker(handshake)
    outcome["thread"].join(5)

    assert outcome.get("cancelled") is True


def test_reset_lets_the_same_handshake_serve_again(qtbot):
    """Without reset an instance serves exactly one prompt, which forecloses asking again."""
    handshake = PinHandshake()

    with qtbot.waitSignal(handshake.requested, timeout=5000):
        first = _ask_from_a_worker(handshake)
    handshake.provide("1111")
    first["thread"].join(5)
    assert first["pin"] == "1111"

    handshake.reset()
    with qtbot.waitSignal(handshake.requested, timeout=5000):
        second = _ask_from_a_worker(handshake)
    handshake.provide("2222")
    second["thread"].join(5)
    assert second["pin"] == "2222"


def test_provide_none_releases_a_worker_parked_on_the_prompt(qtbot):
    """This is what shutdown() uses, so closing the window does not wait out the timeout."""
    handshake = PinHandshake()
    with qtbot.waitSignal(handshake.requested, timeout=5000):
        outcome = _ask_from_a_worker(handshake)

    handshake.provide(None)
    outcome["thread"].join(5)

    assert outcome["thread"].is_alive() is False
    assert outcome.get("cancelled") is True
