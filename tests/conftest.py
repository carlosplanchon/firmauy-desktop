# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Shared fixtures.

The suite never needs a card, a PIN, a reader or a network: the views are exercised against a
stand-in for backend.py, and backend.py's own tests replace the `_api_*` aliases. Widgets are
built for real, headless.
"""

from __future__ import annotations

import os

# Before anything constructs a QApplication. The CI job sets this too, but a developer running
# `pytest` by hand should not have windows flashing past, and a machine with no display should
# not fail to collect.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# On Windows the offscreen plugin has no font database of its own: it looks in Qt's own fonts
# folder, finds nothing, and measures every font, monospace included, as one wide fallback.
# Measured: a sha256 in the mono role came out at 640 px offscreen, against 384 px with the real
# Windows platform (320 px in Consolas). Pointed at the system's fonts, offscreen measures what a
# person would see, and the layout tests ask about this platform rather than about a missing one.
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                                                         "Fonts"))

import pytest                                   # noqa: E402
from PySide6.QtCore import QSettings            # noqa: E402

from firmauy_desktop import backend, settings   # noqa: E402
from firmauy_desktop.ui.theming import theme  # noqa: E402
from tools import cardguard, samples          # noqa: E402


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path):
    """Point QSettings at a throwaway directory, for every test without exception.

    Autouse and not optional: a test that forgot it would write to the developer's real
    ~/.config and, on Windows, into HKCU. Forcing the INI format also makes this the strictest
    case for the coercers in settings.py, since that backend hands every value back as a string.
    """
    previous = QSettings.defaultFormat()
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    yield
    QSettings.setDefaultFormat(previous)


@pytest.fixture(autouse=True)
def isolated_activity_log(tmp_path, monkeypatch):
    """Point the activity record at a throwaway directory, for every test without exception.

    Autouse for the same reason as isolated_settings above, and it needs its own fixture because
    that one is QSettings-specific: it redirects the INI path and touches neither $HOME nor
    QStandardPaths. Measured: QStandardPaths.setTestModeEnabled only moves the answer to
    ~/.qttest, which is still the developer's real home. So a test that turned the record on
    would write there, on every run.

    Left off, since that is the shipped default. A test that wants it calls configure(True).
    """
    from firmauy_desktop import activity

    # A directory that does not exist yet, the way the real state directory may not, so a
    # test can tell "wrote nothing" from "wrote into somewhere pytest had already made".
    monkeypatch.setattr(activity, "log_path", lambda: tmp_path / "estado" / "actividad.log")
    yield
    activity.configure(False)      # never leave a handler open on the next test's tmp_path


@pytest.fixture(scope="session", autouse=True)
def _app_identity(qapp):
    """Set the application up the way app.py does: named, so QSettings has an organisation, and
    themed, so a widget test sees the stylesheet that actually ships rather than bare Qt."""
    settings.apply_identity(qapp)
    qapp.setStyle("Fusion")
    theme.apply(qapp, "light")


class FakeBackend:
    """Replaces backend functions at the view modules' import sites, and records the calls.

    The views do ``from firmauy_desktop.backend import sign_file``, so the name to replace lives
    in the view module, not in ``backend``. Patching ``backend`` itself would have no effect and
    the test would pass while exercising the real thing, which is exactly the green-but-wrong
    failure this helper exists to prevent.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch
        self.calls: list[tuple[str, tuple, dict]] = []

    def patch(self, module, name: str, result=None, *, side_effect=None):
        """Replace ``module.name``. Returns ``result``, or whatever ``side_effect`` returns."""
        def fake(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if side_effect is not None:
                return side_effect(*args, **kwargs)
            return result

        self._monkeypatch.setattr(module, name, fake)
        return fake

    def kwargs_for(self, name: str) -> dict:
        """The keyword arguments of the last call to ``name``."""
        for call_name, _args, kwargs in reversed(self.calls):
            if call_name == name:
                return kwargs
        raise AssertionError(f"{name} was never called")


@pytest.fixture(autouse=True)
def no_real_backend(monkeypatch):
    """Make a test that reaches the real backend fail loudly instead of touching the card.

    The list of card-touching calls lives in ``tools/cardguard.py`` because the storybook needs
    the same guarantee, and a second copy here would drift. Passing ``monkeypatch.setattr`` is
    what makes it per-test; the storybook passes the builtin and it holds for the process.
    """
    cardguard.block_card_calls(monkeypatch.setattr)


@pytest.fixture
def fake_backend(monkeypatch):
    return FakeBackend(monkeypatch)


@pytest.fixture
def make_view(qtbot):
    """Build a view, register it with qtbot, and stop its workers before it is destroyed.

    This mirrors what MainWindow.closeEvent does, so a test exercises the same teardown the app
    performs rather than a shortcut. It matters most for the screens that leave a second task
    running after the one the test waited on: Diagnóstico chains the reader list onto its own
    runner once the checks come back, so waiting for the checks is not waiting for the screen.

    It is not what keeps a running QThread from being collected, though; tasks.py holds those
    itself, because a runner can vanish in plenty of places a fixture never sees.

    Tears down before qtbot's own cleanup, because it is set up after it.
    """
    views = []

    def build(factory, *args, **kwargs):
        view = factory(*args, **kwargs)
        qtbot.addWidget(view)
        views.append(view)
        return view

    yield build

    for view in views:
        shutdown = getattr(view, "shutdown", None)
        if shutdown is not None:
            shutdown()


def widget_text(widget) -> str:
    """Every label under ``widget``, in construction order, newline joined.

    The test-side mirror of what a person reads, and what most assertions became when the screens
    stopped rendering their output as HTML: ``view._signers.text()`` turned into
    ``widget_text(view._signers)`` and the intention survived word for word.

    Includes labels inside a collapsed section, because the text is there either way. Whether
    something is *shown* is a separate question, and CONTRIBUTING says to ask it with isHidden():
    isVisible() is always False when no window has been shown.
    """
    from PySide6.QtWidgets import QLabel

    labels = ([widget] if isinstance(widget, QLabel) else []) + widget.findChildren(QLabel)
    return "\n".join(lbl.text() for lbl in labels if lbl.text())


@pytest.fixture
def sample_identity() -> backend.Identity:
    """Synthetic only, and defined once for the whole repo in ``tools/samples.py``.

    CONTRIBUTING forbids real names, numbers, MRZ data or photos anywhere. Having exactly one
    synthetic cardholder is what makes that rule enforceable rather than aspirational.
    """
    return samples.identity()
