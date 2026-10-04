# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the Mi cédula screen.

The fixtures are synthetic: CONTRIBUTING forbids real names, numbers, MRZ data or photos.
"""

from __future__ import annotations

from conftest import widget_text
from firmauy_desktop import backend
from firmauy_desktop.views import identity_view

# A one-pixel JPEG is enough: nothing here decodes it, and QPixmap simply refuses.
_JPEG = b"\xff\xd8\xff\xdb\x00\x43\x00" + b"\x00" * 64 + b"\xff\xd9"


def _identity(sample_identity, **kw):
    for key, value in kw.items():
        setattr(sample_identity, key, value)
    return backend.IdentityResult(True, sample_identity)


def test_reading_the_card_shows_the_data(make_view, qtbot, fake_backend, sample_identity):
    fake_backend.patch(identity_view, "read_identity", _identity(sample_identity))

    view = make_view(identity_view.IdentityView)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_read()

    data = widget_text(view._data) + "\n" + view._name.text()
    assert "JUANA MARÍA PÉREZ GONZÁLEZ" in data
    assert "1.234.567-2" in data
    assert "Nº de documento" in data          # the card's number, not the cédula number
    assert view._status.isHidden() is True


def test_the_photo_metadata_is_shown(make_view, qtbot, fake_backend, sample_identity):
    """Useful for comparing a saved copy against what the card actually holds."""
    fake_backend.patch(identity_view, "read_identity", _identity(
        sample_identity, photo=_JPEG,
        photo_meta=backend.Photo("JPEG", "image/jpeg", 240, 320, 4096, "abc123def456")))

    view = make_view(identity_view.IdentityView)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_read()

    meta = widget_text(view._photo_meta)
    assert "240 x 320" in meta
    assert "4,0 KB" in meta
    assert "JPEG" in meta

    # The digest is one fold below, not on the same line. It serves one rare errand, checking an
    # exported copy against the card, and it was sixty-four characters wide next to a line that
    # is read at a glance.
    assert "abc123def456" not in meta
    assert "abc123def456" in widget_text(view._photo_digest)
    assert view._digest_box.isHidden() is False
    assert view._digest_box.is_expanded() is False


def test_a_card_without_a_photo_still_shows_the_data(make_view, qtbot, fake_backend,
                                                     sample_identity):
    fake_backend.patch(identity_view, "read_identity",
                       _identity(sample_identity, photo=None, photo_meta=None))

    view = make_view(identity_view.IdentityView)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_read()

    assert view._name.text() == "JUANA MARÍA PÉREZ GONZÁLEZ"
    assert widget_text(view._photo_meta) == ""
    assert view._save_btn.isHidden() is True


def test_a_failure_clears_the_card(make_view, qtbot, fake_backend, sample_identity):
    fake_backend.patch(identity_view, "read_identity", _identity(sample_identity, photo=_JPEG))
    view = make_view(identity_view.IdentityView)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_read()
    assert widget_text(view._data) != ""

    fake_backend.patch(identity_view, "read_identity",
                       backend.IdentityResult(False, error="No se detectó la cédula.",
                                              error_kind="card"))
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_read()

    assert widget_text(view._data) == ""      # no stale data from the previous card
    assert view._name.text() == ""
    assert widget_text(view._photo_meta) == ""
    assert "No se detectó la cédula." in widget_text(view._status)


# --- the cédula number checker ----------------------------------------------

def test_a_partial_number_gets_its_check_digit(make_view, qtbot, fake_backend, monkeypatch):
    monkeypatch.setattr(identity_view, "check_ci",
                        lambda text: backend.CiResult("Con dígito verificador: 12345672",
                                                      completed="12345672"))

    view = make_view(identity_view.IdentityView)
    view._ci_input.setText("1234567")

    assert "12345672" in widget_text(view._ci_message)


def test_a_consistent_number_is_marked_green(make_view, qtbot, fake_backend, monkeypatch):
    monkeypatch.setattr(identity_view, "check_ci",
                        lambda text: backend.CiResult("El número es consistente.", ok=True))

    view = make_view(identity_view.IdentityView)
    view._ci_input.setText("12345672")

    # A tone rather than a hex value: it survives a change of palette, reads the same in both
    # schemes, and fails if the map ever paints a rejected number green.
    assert view._ci_message.property("tone") == "ok"


def test_an_inconsistent_number_is_marked_red(make_view, qtbot, fake_backend, monkeypatch):
    monkeypatch.setattr(identity_view, "check_ci",
                        lambda text: backend.CiResult("No es consistente.", ok=False))

    view = make_view(identity_view.IdentityView)
    view._ci_input.setText("12345679")

    assert view._ci_message.property("tone") == "bad"


def test_clearing_the_field_clears_the_message(make_view, qtbot, fake_backend):
    view = make_view(identity_view.IdentityView)
    view._ci_input.setText("1234567")
    assert widget_text(view._ci_message) != ""

    view._ci_input.setText("")
    assert widget_text(view._ci_message) == ""


def test_the_field_reduces_what_arrives_to_its_digits(make_view, qtbot, fake_backend):
    """The national written form is "1.234.567-8" and gets pasted that way: the separators
    reduce away, letters vanish because they have nothing to reduce to, and a ninth digit has
    nowhere to go."""
    view = make_view(identity_view.IdentityView)

    view._ci_input.setText("1.234.567-2")
    assert view._ci_input.text() == "12345672"
    assert view._ci_message.property("tone") == "ok"

    view._ci_input.setText("asdsadsad")
    assert view._ci_input.text() == ""
    assert widget_text(view._ci_message) == ""

    view._ci_input.setText("123456789")
    assert view._ci_input.text() == "12345678"


def test_the_field_keeps_only_the_digits_a_cedula_is_written_in(make_view, qtbot, fake_backend):
    """'²', '٣' and '４' passed for digits here and in the checker behind it, which answered a
    superscript with a failure it did not recognise. They reduce away like letters do."""
    view = make_view(identity_view.IdentityView)

    view._ci_input.setText("²٣４")
    assert view._ci_input.text() == ""
    assert widget_text(view._ci_message) == ""

    view._ci_input.setText("1234567²")
    assert view._ci_input.text() == "1234567"
    assert "12345672" in widget_text(view._ci_message)


def test_the_checker_runs_against_the_real_helper_on_every_keystroke(make_view, qtbot,
                                                                     fake_backend):
    """No mock here on purpose: check_ci is called per keypress and must never raise, whatever
    is half-typed."""
    view = make_view(identity_view.IdentityView)
    # Every half-typed shape a person passes through, plus the nonsense they can paste in.
    for text in ["1", "1.", "1.2", "1.234.567", "1.234.567-2", "abc", "999999999999", "-", "0"]:
        view._ci_input.setText(text)          # would propagate out of the slot if it raised

    # Nothing escaped the slot, and the field still answers correctly afterwards. Twelve nines
    # are reduced to eight before check_ci ever sees them, so the backend's "hasta 8 dígitos"
    # sentence stays as its own belt rather than as this field's answer.
    view._ci_input.setText("999999999999")
    assert view._ci_input.text() == "99999999"
    assert widget_text(view._ci_message) != ""
    view._ci_input.setText("12345672")
    assert "consistente" in widget_text(view._ci_message)


def test_the_checker_needs_no_card(make_view, qtbot, fake_backend):
    """It is the most-used thing here and it must work with nothing in the reader."""
    fake_backend.patch(identity_view, "read_identity",
                       backend.IdentityResult(False, error="No se detectó la cédula.",
                                              error_kind="card"))

    view = make_view(identity_view.IdentityView)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_read()

    view._ci_input.setText("12345672")
    assert "consistente" in widget_text(view._ci_message)


# --- the photo ---------------------------------------------------------------

def _jpeg(width: int, height: int) -> bytes:
    """A real, decodable JPEG. QPixmap refuses the one-pixel stub above, and these tests are
    about what QPixmap does with the bytes."""
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage

    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#8fa3b8"))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "JPEG")
    return bytes(buffer.data())


def test_a_normal_screen_gets_the_photo_scaled_to_the_box():
    device, ratio = identity_view._photo_scale(source_height=320, dpr=1.0)
    assert device == identity_view._PHOTO_HEIGHT
    assert ratio == 1.0


def test_a_hidpi_screen_gets_every_pixel_the_card_holds():
    """The bug: 220 logical points on a 2x screen is 440 physical pixels, and handing Qt a 220
    pixel image to fill them is exactly the blur this is about."""
    device, ratio = identity_view._photo_scale(source_height=320, dpr=2.0)

    assert device == 320                                  # all of it, not 220
    assert device / ratio == identity_view._PHOTO_HEIGHT   # still 220 points on screen


def test_a_photo_bigger_than_the_box_is_not_read_past_what_the_screen_shows():
    device, ratio = identity_view._photo_scale(source_height=800, dpr=2.0)
    assert (device, ratio) == (440, 2.0)


def test_a_small_photo_is_never_blown_up():
    """A 100 pixel photo stretched to 220 is an invention, and this is the one image where
    somebody is comparing what they see against the plastic in their hand."""
    device, ratio = identity_view._photo_scale(source_height=100, dpr=1.0)
    assert (device, ratio) == (100, 1.0)                  # shown at its own size, not the box's

    device, ratio = identity_view._photo_scale(source_height=100, dpr=2.0)
    assert device == 100                                  # there is no more detail to ask for
    assert device / ratio == 100


def test_a_card_with_no_photo_leaves_no_gap(make_view, qtbot, fake_backend, sample_identity):
    """The box is a fixed 220 points tall. Left in place with nothing in it, a card without a
    photo opened a blank the height of a photo and pushed the rest of the screen down."""
    fake_backend.patch(identity_view, "read_identity", _identity(sample_identity, photo=None))

    view = make_view(identity_view.IdentityView)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_read()

    assert view._photo_label.isHidden() is True


def test_the_photo_box_comes_back_when_there_is_one(make_view, qtbot, fake_backend,
                                                    sample_identity):
    fake_backend.patch(identity_view, "read_identity",
                       _identity(sample_identity, photo=_jpeg(240, 320)))

    view = make_view(identity_view.IdentityView)
    assert view._photo_label.isHidden() is True          # nothing read yet
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_read()

    assert view._photo_label.isHidden() is False


def test_the_rendered_photo_carries_its_device_pixel_ratio(make_view, qtbot, fake_backend,
                                                           sample_identity):
    """Without it Qt draws the pixmap at one point per pixel and the whole calculation is lost."""
    fake_backend.patch(identity_view, "read_identity",
                       _identity(sample_identity, photo=_jpeg(240, 320)))

    view = make_view(identity_view.IdentityView)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_read()

    pixmap = view._photo_label.pixmap()
    assert not pixmap.isNull()
    assert pixmap.devicePixelRatio() > 0
    assert pixmap.height() / pixmap.devicePixelRatio() == identity_view._PHOTO_HEIGHT


def test_the_photo_survives_being_shown_again(make_view, qtbot, fake_backend, sample_identity):
    """showEvent redraws it, because the device pixel ratio only answers for real once the widget
    is on a screen, and it changes again when the window moves to another one."""
    from PySide6.QtGui import QShowEvent

    fake_backend.patch(identity_view, "read_identity",
                       _identity(sample_identity, photo=_jpeg(240, 320)))

    view = make_view(identity_view.IdentityView)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_read()
    view.showEvent(QShowEvent())

    assert not view._photo_label.pixmap().isNull()


def test_a_photo_without_a_digest_shows_no_fold(make_view, qtbot, fake_backend, sample_identity):
    """An empty collapsible is a control that promises something and has nothing."""
    fake_backend.patch(identity_view, "read_identity", _identity(
        sample_identity, photo=_jpeg(240, 320),
        photo_meta=backend.Photo("JPEG", "image/jpeg", 240, 320, 4096, "")))

    view = make_view(identity_view.IdentityView)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_read()

    assert view._digest_box.isHidden() is True
    assert "240 x 320" in widget_text(view._photo_meta)


# --- the two states of the screen --------------------------------------------

def test_the_read_data_lives_inside_a_card(make_view, qtbot, fake_backend, sample_identity):
    """What came off the card is one thing, and a titled surface is how this app groups one
    thing. Photo and data used to sit on the bare background as loose widgets, on the screen
    that shows somebody their own document.

    Hidden until there is something to hold: an empty framed box is a box waiting for content.
    """
    fake_backend.patch(identity_view, "read_identity", _identity(sample_identity, photo=_JPEG))
    view = make_view(identity_view.IdentityView)

    assert view._identity_card.isHidden() is True

    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_read()

    assert view._identity_card.isHidden() is False
    assert "JUANA MARÍA PÉREZ GONZÁLEZ" in widget_text(view._identity_card)


def test_after_a_read_the_button_steps_aside(make_view, qtbot, fake_backend, sample_identity):
    """Before a read it is the screen's one action. After a successful one the task is done and
    the content is the point, so a full-width primary button over somebody's own data kept
    advertising a step that already happened."""
    fake_backend.patch(identity_view, "read_identity", _identity(sample_identity))
    view = make_view(identity_view.IdentityView)

    assert view._button.text() == "Leer mi cédula"
    assert view._button.property("variant") == "primary"

    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_read()

    assert view._button.text() == "Volver a leer"
    assert view._button.property("variant") != "primary"


def test_a_failed_read_puts_the_entry_action_back(make_view, qtbot, fake_backend,
                                                  sample_identity):
    """A failure clears the result, so the screen is back in its entry state and the button has
    to say so too: "Volver a leer" over no data describes a step that no longer happened."""
    fake_backend.patch(identity_view, "read_identity", _identity(sample_identity))
    view = make_view(identity_view.IdentityView)
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_read()
    assert view._button.text() == "Volver a leer"

    fake_backend.patch(identity_view, "read_identity",
                       backend.IdentityResult(False, error="No se detectó la cédula.",
                                              error_kind="card"))
    with qtbot.waitSignal(view._runner.finished, timeout=5000):
        view._on_read()

    assert view._button.text() == "Leer mi cédula"
    assert view._button.property("variant") == "primary"
    assert view._identity_card.isHidden() is True
