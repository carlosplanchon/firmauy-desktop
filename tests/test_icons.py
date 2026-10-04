# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the icon set.

The one that earns its place is ``test_every_icon_renders``. Qt renders SVG Tiny 1.2, and an
icon with a `<style>` block, a CSS class or a filter comes back as a **blank image with no
error at all**. Checking that loading did not raise would pass on a file that draws nothing, so
these count opaque pixels instead.
"""

from __future__ import annotations

import pytest

from firmauy_desktop.ui import icons, tokens
from firmauy_desktop.ui.theming import theme


def _opaque(pixmap) -> int:
    image = pixmap.toImage()
    return sum(1 for x in range(image.width()) for y in range(image.height())
               if image.pixelColor(x, y).alpha() > 30)


def test_there_is_an_icon_set(qapp):
    assert len(icons.names()) >= 14


@pytest.mark.parametrize("name", icons.names())
def test_every_icon_actually_draws_something(qapp, name):
    """A blank render is what an unsupported SVG feature looks like, and it is silent."""
    assert _opaque(icons.pixmap(name, "fg.default", 16)) > 10, name


@pytest.mark.parametrize("name", icons.names())
def test_every_icon_is_svg_tiny_safe(name):
    """The features Qt's renderer does not support, checked in the source rather than by eye."""
    source = (icons.ICON_DIR / f"{name}.svg").read_text(encoding="utf-8")
    for unsupported in ("<style", "class=", "filter", "currentColor", "<mask", "<use"):
        assert unsupported not in source, f"{name}.svg uses {unsupported}"


def test_an_icon_is_painted_in_the_tone_it_was_asked_for(qapp):
    theme.set_preference("light")
    image = icons.pixmap("check", "status.bad", 24).toImage()
    solid = [image.pixelColor(x, y).name()
             for x in range(image.width()) for y in range(image.height())
             if image.pixelColor(x, y).alpha() > 240]
    assert solid, "nothing opaque enough to check the colour of"
    assert solid[0] == theme.hex("status.bad")


def test_the_same_icon_comes_out_different_in_each_scheme(qapp):
    """The tint is baked into the pixmap, so a stale cache would ship the wrong colour."""
    theme.set_preference("light")
    light = icons.pixmap("check", "status.ok", 16).toImage()
    theme.set_preference("dark")
    dark = icons.pixmap("check", "status.ok", 16).toImage()
    theme.set_preference("light")
    assert light != dark


def test_changing_the_scheme_drops_what_was_painted_with_the_old_palette(qapp):
    """Every tint in there was painted with the old palette, so keeping any of it would ship the
    wrong colour until the app restarted.

    Asserted on the identity of one entry rather than on the cache being empty afterwards. Empty
    is not the invariant and is not even reliably true: clear_cache runs first, and then every
    live icon label repaints itself on the same signal and fills the cache back up, with the new
    colours. Whether that happens depends on which widgets other tests left alive.
    """
    theme.set_preference("light")
    key = ("check", "status.ok", 16, 1.0)
    painted_in_light = icons.pixmap(*key)
    assert icons._cache[key] is painted_in_light

    theme.set_preference("dark")

    # Gone, or replaced by a repaint. Never the same object, which is what a missing
    # theme.changed -> clear_cache connection would leave behind.
    assert icons._cache.get(key) is not painted_in_light
    theme.set_preference("light")


def test_clearing_the_cache_empties_it(qapp):
    icons.pixmap("check", "status.ok", 16)
    assert icons._cache

    icons.clear_cache()

    assert icons._cache == {}


def test_a_missing_icon_is_a_gap_not_a_crash(qapp):
    """app.py already treats a missing window icon as cosmetic. Same instinct: a screen with one
    blank space still does its job.

    It used to say so with a print to stdout, which a packaged build has nowhere to put: the spec
    sets console=False. It goes to the activity record now, so the report survives where it is
    needed and costs nothing when the record is off, which is the default.
    """
    from firmauy_desktop import activity

    activity.configure(True)
    assert icons.pixmap("no-existe-este-icono").isNull()
    assert icons.icon("no-existe-este-icono").isNull()

    # Recorded, and the name redacted, because it is not one of the icons this app ships. A name
    # that is not in the set came from somebody's code rather than from the package, and the
    # record's domains do not make an exception for the field that reports a miss.
    written = activity.log_path().read_text(encoding="utf-8")
    assert "icono no encontrado" in written
    assert f"name={activity.REDACTED}" in written
    assert "no-existe-este-icono" not in written


def test_an_icon_missing_from_the_install_is_named(qapp, monkeypatch, tmp_path):
    """The failure this event exists for: the file is one of the app's own and is not on disk,
    which is a packaging problem and needs the name to be actionable. That name is in the set, so
    it is written, unlike the invented one above."""
    from firmauy_desktop import activity

    monkeypatch.setattr(icons, "ICON_DIR", tmp_path)      # every icon suddenly absent
    icons._missing.clear()
    activity.configure(True)

    assert icons.pixmap("check").isNull()
    assert "name=check" in activity.log_path().read_text(encoding="utf-8")


def test_a_missing_icon_is_only_reported_once(qapp, monkeypatch, tmp_path):
    """Counted on an icon this app really ships, since that is the name the record writes. An
    invented one is redacted, so counting it would be counting the marker."""
    from firmauy_desktop import activity

    monkeypatch.setattr(icons, "ICON_DIR", tmp_path)
    icons._missing.clear()
    activity.configure(True)

    for _ in range(3):
        icons.pixmap("warning")
    assert activity.log_path().read_text(encoding="utf-8").count("name=warning") == 1


def test_every_status_has_its_own_icon_and_tone(qapp):
    """Not merely "an icon": a missing entry falls back to the neutral dot, which reads as "not
    done yet" and is exactly how the three verdicts shipped looking identical."""
    assert set(tokens.STATUS_ICON) == set(tokens.STATUS_TONE)
    for status, name in tokens.STATUS_ICON.items():
        assert name in icons.names(), f"{status} wants {name}.svg"
        assert name != "dot", f"{status} falls back to the neutral icon"


def test_the_two_vocabularies_agree(qapp):
    """firmauy says PASS/WARN/FAIL about the environment and VALID/INDETERMINATE/INVALID about a
    signature. The same meaning has to look the same."""
    for good, bad in (("PASS", "VALID"), ("WARN", "INDETERMINATE"), ("FAIL", "INVALID")):
        assert tokens.STATUS_ICON[good] == tokens.STATUS_ICON[bad]
        assert tokens.STATUS_TONE[good] == tokens.STATUS_TONE[bad]


def test_the_icons_the_widgets_ask_for_all_exist(qapp):
    """The four batch statuses and the two chevrons, named as strings in widgets.py."""
    from firmauy_desktop.widgets import FileListWidget

    for name, _tone, _spoken in FileListWidget._ICON.values():
        assert name in icons.names(), name
    assert {"chevron-down", "chevron-right"} <= set(icons.names())
