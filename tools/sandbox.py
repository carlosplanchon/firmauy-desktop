# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""A settings store of the tools' own, for the length of one run.

The screenshot tool and the storybook build the real screens, and the real screens read the
settings as they start and write them as they close. Run on somebody's machine, they rendered that
person's choices: measured, the README's four images all came out different with nothing changed
but the store, because one of those choices was showing Avanzado. And the screenshot tool closes a
MainWindow per image, each of which saved its geometry over the one the person had left.

Pointed at a directory of its own before anything constructs a QSettings, so what renders is the
same on every machine and nothing of the person's is read or written.
"""

from __future__ import annotations

import tempfile
from typing import Optional

from PySide6.QtCore import QSettings

from firmauy_desktop import settings

# Held for the whole run. The directory goes when this object does, at interpreter exit at the
# latest, so a run leaves nothing behind.
_STORE: Optional[tempfile.TemporaryDirectory] = None


def isolate_settings(seed: Optional[settings.Settings] = None) -> str:
    """Point QSettings at a fresh directory, write ``seed`` into it when given, return its path.

    After ``settings.apply_identity`` and before the first screen is built: a QSettings keeps the
    location it was constructed with, so one made earlier would still reach the person's own.
    """
    global _STORE
    _STORE = tempfile.TemporaryDirectory(prefix="firmauy-tools-")
    # The INI format everywhere, the strictest case for the loaders, as in the test suite.
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, _STORE.name)
    if seed is not None:
        settings.save(seed)
    return _STORE.name
