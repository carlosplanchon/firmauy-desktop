# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""The PIN round trip between the worker thread and the UI thread.

The PIN is never collected up front. firmauy checks the reader, the card and the certificate
first, and only then calls back for it, so a setup that cannot sign never costs one of the
card's limited tries. That callback runs on the worker thread, and Qt forbids touching widgets
from there, which is what this class bridges.
"""

from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import QObject, Signal

from firmauy_desktop.backend import PinCancelled

# Safety net: if the prompt never answers (it is modal, so this should not happen), the worker
# gives up instead of parking forever and holding the card session open.
PIN_TIMEOUT_SECONDS = 300


class PinHandshake(QObject):
    """Hands a ``pin_provider`` to the backend and gets the PIN back from a dialog.

    ``provider`` is what goes to the backend. firmauy invokes it **on the worker thread**, after
    the PIN-free certificate read. It emits ``requested``, blocks, and returns the PIN handed
    back through ``provide``. The PIN is dropped the instant it is returned, so it never sits on
    this object afterwards.

    Connect ``requested`` with an explicit ``Qt.ConnectionType.QueuedConnection``. Auto would
    resolve to the same thing today, but saying it means a later refactor cannot end up opening
    a modal dialog on the worker thread. The consequence is that calling ``provider()`` from the
    UI thread deadlocks, which is correct: it is only ever meant to be called from a worker.
    """

    requested = Signal()

    def __init__(self, timeout_seconds: int = PIN_TIMEOUT_SECONDS,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._timeout = timeout_seconds
        self._pin: Optional[str] = None
        self._ready = threading.Event()

    def provider(self) -> str:
        """Called by the backend on the worker thread. Raises PinCancelled if there is no PIN."""
        self.requested.emit()
        if not self._ready.wait(timeout=self._timeout):
            raise PinCancelled
        pin, self._pin = self._pin, None    # do not keep the PIN around after handing it over
        if not pin:
            raise PinCancelled
        return pin

    def provide(self, pin: Optional[str]) -> None:
        """Called on the UI thread with the PIN entered, or None when it was dismissed.

        Also the way to release a worker parked on the prompt while the window is closing.
        """
        self._pin = pin
        self._ready.set()

    def reset(self) -> None:
        """Clear the handshake so the same object can serve another prompt.

        Without this an instance serves exactly one, which silently forecloses asking again
        after a wrong PIN.
        """
        self._pin = None
        self._ready.clear()
