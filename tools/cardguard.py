# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""The one list of backend calls that end up talking to the card.

It lives here, outside the package, because two things need it and neither may own it: the test
suite, which must never reach a real cédula, and the storybook, whose entire purpose is to
iterate on the UI without inserting one. Keeping the list in `tests/` would mean the storybook
either imported from the test tree or kept a second copy that drifts.
"""

from __future__ import annotations

import importlib
from typing import Callable

# Per view module, because that is where the name the view calls actually lives: the views do
# `from firmauy_desktop.backend import sign_file`, so replacing it on `backend` would have no
# effect at all.
REAL_WORK: dict[str, tuple[str, ...]] = {
    "sign_view": ("sign_file", "sign_batch"),
    "verify_view": ("verify_file", "verify_batch"),
    "identity_view": ("read_identity",),
    "doctor_view": ("run_doctor", "list_readers", "refresh_cas"),
    "advanced_view": ("list_tokens", "list_certs"),
}


def block_card_calls(set_attr: Callable[[object, str, object], None] = setattr) -> None:
    """Replace every card-touching call with one that fails loudly.

    ``set_attr`` is how the replacement is installed: pytest passes ``monkeypatch.setattr`` so it
    is undone per test, the storybook passes the builtin so it holds for the whole process.

    This exists because it already happened. A screen took a code path the test author had not
    anticipated, landed on a function that test had not replaced, and ran a real signature
    against a real cédula with a made-up PIN, which spends one of the card's limited tries.
    Being careful does not prevent that; a net does.
    """
    for module_name, names in REAL_WORK.items():
        module = importlib.import_module(f"firmauy_desktop.views.{module_name}")
        for name in names:
            set_attr(module, name, _refuse(module_name, name))


def _refuse(module_name: str, name: str) -> Callable[..., object]:
    def refuse(*args, **kwargs):
        raise AssertionError(
            f"{module_name} called the real backend.{name}(). Nothing outside the app itself may "
            f"reach the card: replace it with fake_backend.patch({module_name}, {name!r}, ...) in "
            f"a test, or drive the screen from tools.samples in the storybook. If the screen got "
            f"here by a path you did not expect, that is the bug this caught."
        )

    return refuse
