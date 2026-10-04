# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""The icon set: hand-written SVG, tinted to a token.

Icons, never emoji, and for portability rather than taste: the warning sign is two codepoints
(U+26A0 plus a variation selector), the white bullet is a tofu candidate on Windows, and
colour-font emoji ignore CSS `color` entirely, which splits status colour into two incompatible
systems at once.

**The constraint that will bite whoever edits an icon: Qt renders SVG Tiny 1.2.** No `<style>`
block, no CSS classes, no filters, no masks, no `currentColor`. An icon exported from a design
tool with a `<style>` block renders as a blank image and raises nothing at all, which is why the
test counts opaque pixels rather than checking that loading did not throw.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

from firmauy_desktop import activity
from firmauy_desktop.ui.theming import theme

ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"

# The app's own mark, as opposed to the set above. It lives inside the package so one path works
# from a source checkout, an installed wheel and a PyInstaller bundle alike.
#
# The SVG first and the PNG behind it: Qt draws the vector at whatever size is asked for, where a
# single 512 pixel PNG has to be resampled, and at 16 points the chip's gutters disappear into the
# blur. The PNG stays because it is the original artwork and what the Linux desktop entry names.
APP_ICON_SOURCES = (ICON_DIR.parent / "icon.svg", ICON_DIR.parent / "icon.png")

_cache: dict[tuple[str, str, int, float], QPixmap] = {}
_missing: set[str] = set()


LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"


def logo(height: int) -> QPixmap:
    """The project's full logo lockup, scaled to `height`.

    The whole image, unaltered, in both schemes. The artwork is drawn on white, so on the dark
    scheme it shows as a white panel. Left square on purpose: rounding it was tried and read as
    a soft badge rather than as the drawing it is.

    Null when the file is missing, like :func:`app_icon`. A dialog without its picture is still a
    dialog, and refusing to open one over a decoration would be the wrong trade.
    """
    source = _logo_source()
    if source is None:
        return QPixmap()
    return source.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)


@lru_cache(maxsize=1)
def _logo_source() -> Optional[QPixmap]:
    """The artwork, decoded once.

    Measured at 4.4 ms a time against 1.5 ms to scale it, and Acerca de asks for several sizes
    while it works out which one matches its text. Decoding the same file for each of them was
    most of what opening that dialog cost.
    """
    if not LOGO_PATH.is_file():
        return None
    source = QPixmap(str(LOGO_PATH))
    return None if source.isNull() else source


def app_icon() -> QIcon:
    """The app's mark, for the window and the sidebar.

    Null when nothing is there, which every caller already treats as cosmetic rather than as a
    reason not to start. Null also if the Qt svg plugin is missing from a bundle, hence the
    fallback: an icon that renders nothing is the same to a person as one that is absent.
    """
    for path in APP_ICON_SOURCES:
        if not path.is_file():
            continue
        icon = QIcon(str(path))
        # isNull, not availableSizes: a scalable icon reports no fixed sizes and is not empty.
        if not icon.isNull():
            return icon
    return QIcon()


def names() -> list[str]:
    """Every icon that exists, for the test that renders them all."""
    return sorted(path.stem for path in ICON_DIR.glob("*.svg"))


def clear_cache() -> None:
    """Called when the scheme changes: every tint in here is the old palette's."""
    _cache.clear()


def pixmap(name: str, tone: str = "fg.default", size: int = 18, dpr: float = 1.0) -> QPixmap:
    """The icon at one size, painted in the colour of ``tone``.

    Tinting is done by composition rather than by editing the SVG: every opaque pixel is replaced
    with the colour, which works because these are all single-colour shapes. `QIcon.pixmap` is
    given the device pixel ratio, so it renders the vector at the real pixel size instead of
    scaling a smaller raster up, and HiDPI is right by construction.
    """
    key = (name, tone, size, dpr)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    path = ICON_DIR / f"{name}.svg"
    if not path.is_file():
        # A missing icon is a blank space, never a crash: app.py has the same instinct for the
        # window icon, and a screen with one gap still does its job.
        if name not in _missing:
            _missing.add(name)
            activity.event("icono no encontrado", name=name)
        return QPixmap()

    result = QIcon(str(path)).pixmap(QSize(size, size), dpr)
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(result.rect(), theme.color(tone))
    painter.end()
    _cache[key] = result
    return result


def icon(name: str, tone: str = "fg.default", size: int = 18) -> QIcon:
    """The tinted icon, with a 1x and a 2x pixmap so Qt picks per screen."""
    result = QIcon()
    for ratio in (1.0, 2.0):
        rendered = pixmap(name, tone, size, ratio)
        if not rendered.isNull():
            result.addPixmap(rendered)
    return result


def status_icon(status: str, size: int = 18) -> QIcon:
    """The icon and colour for a PASS / WARN / FAIL, or a VALID / INDETERMINATE / INVALID."""
    from firmauy_desktop.ui import tokens

    name = tokens.STATUS_ICON.get(status, "dot")
    tone = tokens.STATUS_TONE.get(status)
    return icon(name, f"status.{tone}" if tone else "fg.muted", size)


theme.changed.connect(clear_cache)
