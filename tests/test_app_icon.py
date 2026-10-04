# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the app's own mark and the containers built from it.

The SVG is the source and the .ico and .icns are generated from it, so what is worth checking is
that the generated files still match the vector and that Qt can read every one of them back. A
committed binary that has drifted from its source is exactly the kind of thing nobody notices
until a release.
"""

from __future__ import annotations

import struct

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

from firmauy_desktop.ui import icons

ASSETS = icons.ICON_DIR.parent


def _opaque(image: QImage) -> int:
    return sum(1 for x in range(image.width()) for y in range(image.height())
               if image.pixelColor(x, y).alpha() > 30)


def test_the_svg_is_the_source_and_it_renders(qapp):
    assert (ASSETS / "icon.svg").is_file()
    # Same trap as the icon set: an SVG Qt cannot parse comes back blank and raises nothing.
    assert _opaque(icons.app_icon().pixmap(QSize(64, 64)).toImage()) > 500


def test_the_svg_is_svg_tiny_safe(qapp):
    source = (ASSETS / "icon.svg").read_text(encoding="utf-8")
    for unsupported in ("<style", "class=", "filter", "currentColor", "<mask", "<use"):
        assert unsupported not in source


@pytest.mark.parametrize("size", [16, 24, 32, 64, 256])
def test_the_icon_draws_something_at_every_size_it_is_asked_for(qapp, size):
    """The reason for having a vector at all: a 512 pixel PNG resampled to 16 loses the chip's
    gutters, and what is left is a blue blob."""
    assert _opaque(icons.app_icon().pixmap(QSize(size, size)).toImage()) > size


def test_the_app_icon_prefers_the_vector(qapp):
    assert icons.APP_ICON_SOURCES[0].name == "icon.svg"
    assert icons.APP_ICON_SOURCES[1].name == "icon.png"     # still there, still the fallback


def test_a_missing_icon_is_not_a_reason_not_to_start(qapp, monkeypatch, tmp_path):
    """app.py has always treated this as cosmetic. Two sources rather than one must not change
    that into two ways to fail."""
    monkeypatch.setattr(icons, "APP_ICON_SOURCES", (tmp_path / "nada.svg", tmp_path / "nada.png"))
    assert icons.app_icon().isNull()


# --- the generated containers ------------------------------------------------

def test_the_ico_carries_every_size_windows_asks_for(qapp):
    data = (ASSETS / "icon.ico").read_bytes()
    count = struct.unpack("<H", data[4:6])[0]
    sizes = {data[6 + i * 16] or 256 for i in range(count)}

    from tools.make_icons import ICO_SIZES
    assert sizes == set(ICO_SIZES)


def test_the_icns_is_a_container_qt_can_read(qapp):
    path = ASSETS / "icon.icns"
    assert path.read_bytes()[:4] == b"icns"
    assert not QImage(str(path)).isNull()


def _pixels(payload: bytes) -> bytes:
    """One PNG payload as raw RGBA, so two of them can be compared as pictures.

    Format_RGBA8888 at these sizes has no scanline padding, so the buffer is exactly
    width * height * 4 and a byte-for-byte comparison of it is a pixel-for-pixel one.
    """
    image = QImage()
    assert image.loadFromData(payload, "PNG"), "a payload Qt cannot decode"
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    # Named rather than chained: constBits() is a view into the QImage's own buffer, and a
    # temporary would be free to die before bytes() has finished copying out of it.
    return bytes(converted.constBits())


def _worst_channel_difference(a: bytes, b: bytes) -> int:
    assert len(a) == len(b), "different pixel counts"
    if a == b:
        return 0                              # the ordinary case, and the cheap one
    return max(abs(x - y) for x, y in zip(a, b))


@pytest.mark.parametrize("name, build, payloads", [
    ("icon.ico", "build_ico", "ico_payloads"),
    ("icon.icns", "build_icns", "icns_payloads"),
])
def test_the_containers_are_still_what_the_svg_says(qapp, name, build, payloads):
    """Regenerated and compared rather than trusted. They are committed binaries built from a
    text file, which is the shape of thing that quietly goes stale.

    Compared as pictures, not as bytes. This read the two files with ``==`` until a run on a
    different PySide6 failed it over twelve pixels that differed by one level of one channel: Qt
    had rasterised the same vector very slightly differently. That is a true statement about the
    build environment and a useless one about these files, and a test that fails on it teaches
    people to regenerate the binaries to make it quiet, which is how a real drift gets committed.

    So the structure is still exact -- the same chunks, at the same sizes, each one decodable --
    and the pixels are allowed one level of slack per channel and no more. Nothing an actual
    change to the vector can do fits inside that: move a gutter, change the blue, drop a size,
    and the difference is tens of levels or a missing key, not one.
    """
    from tools import make_icons

    committed = getattr(make_icons, payloads)((ASSETS / name).read_bytes())
    rebuilt = getattr(make_icons, payloads)(getattr(make_icons, build)())

    assert committed.keys() == rebuilt.keys()
    for key in committed:
        worst = _worst_channel_difference(_pixels(committed[key]), _pixels(rebuilt[key]))
        assert worst <= 1, f"{name} {key} drifted from the SVG by {worst} levels"


# --- the frozen-build check --------------------------------------------------

def test_the_icon_selftest_passes_from_source(qapp, capsys, monkeypatch):
    """The check a frozen build runs. Exercised here too, so the check itself cannot rot: it is
    the only thing that would tell a working bundle from one that silently draws nothing."""
    from firmauy_desktop import app

    monkeypatch.setattr(app, "QApplication", lambda argv: qapp)
    assert app._selftest_icons() == 0
    assert "0 en blanco" in capsys.readouterr().out


def test_the_icon_selftest_fails_when_an_icon_comes_out_blank(qapp, capsys, monkeypatch):
    """Otherwise it is a check that always says yes, which is worse than no check at all."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap

    from firmauy_desktop import app

    def blank(*_a, **_k):
        # Filled, not merely constructed: a fresh QPixmap holds undefined bytes, and the first
        # version of this test passed because that garbage happened to come out opaque.
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        return pixmap

    monkeypatch.setattr(app, "QApplication", lambda argv: qapp)
    monkeypatch.setattr(icons, "pixmap", blank)

    assert app._selftest_icons() == 1


# --- the frozen-build verification check -------------------------------------

class _Check:
    def __init__(self, name, ok):
        self.name, self.ok, self.detail = name, ok, ""


class _Signature:
    def __init__(self, checks, common_name="ALGUIEN"):
        self.checks = checks
        self.signer = {"common_name": common_name}


class _Report:
    def __init__(self, indication, signatures):
        self.indication, self.signatures = indication, signatures


def _real_work(chain_ok=False):
    """The four checks a signed PDF really produces, so a case built on them differs from the
    fixture in exactly the one way it means to."""
    return [
        _Check("signature intact (covered bytes unmodified)", True),
        _Check("signature cryptographically valid", True),
        _Check("coverage (whole file)", True),
        _Check("certificate chain to trusted root", chain_ok),
    ]


def _fixture_shaped():
    """What the generated fixture really produces, measured: three checks pass and the chain is
    the only one that fails."""
    return _Report("INDETERMINATE", [_Signature([
        _Check("signature intact (covered bytes unmodified)", True),
        _Check("signature cryptographically valid", True),
        _Check("coverage (whole file)", True),
        _Check("certificate chain to trusted root", False),
    ], "FIXTURE SINTETICA DE PRUEBA, NO ES UNA PERSONA")])


def _run(monkeypatch, report, expected="INDETERMINATE") -> int:
    import firmauy.api

    from firmauy_desktop import app

    monkeypatch.setattr(firmauy.api, "verify", lambda path, **kw: report)
    return app._selftest_verify("no importa.pdf", expected)


def test_the_verify_selftest_accepts_the_shape_the_fixture_really_has(monkeypatch, capsys):
    assert _run(monkeypatch, _fixture_shaped()) == 0
    written = capsys.readouterr().out
    assert "firmas=1" in written and "FIXTURE SINTETICA" in written


def test_the_verify_selftest_is_not_satisfied_by_the_indication_alone(monkeypatch):
    """The reason this checks anything past the verdict at all.

    INDETERMINATE is also where a file the verifier cannot make sense of ends up, so a bundle
    that had lost the ability to read a signature would pass by failing in the expected
    direction. Each of these lands on the expected verdict and on nothing else.
    """
    ninguna = _Report("INDETERMINATE", [])
    assert _run(monkeypatch, ninguna) == 1, "sin firmas y con el veredicto correcto"

    dos = _Report("INDETERMINATE", [_Signature(_real_work()), _Signature(_real_work())])
    assert _run(monkeypatch, dos) == 1, "dos firmas donde la fixture tiene una"

    sin_nombre = _Report("INDETERMINATE", [_Signature(_real_work(), "")])
    assert _run(monkeypatch, sin_nombre) == 1, "el certificado no dio un nombre"

    todo_mal = _Report("INDETERMINATE", [_Signature([
        _Check("signature intact", False),
        _Check("certificate chain to trusted root", False),
    ])])
    assert _run(monkeypatch, todo_mal) == 1, "la firma en sí tampoco se sostiene"

    # The gap a count of failures leaves open: a build that found a signature, read a name off its
    # certificate, failed the chain and did nothing else at all. One failure, the expected verdict,
    # and no evidence that a single byte was ever verified.
    nada_verificado = _Report("INDETERMINATE", [_Signature([
        _Check("certificate chain to trusted root", False)])])
    assert _run(monkeypatch, nada_verificado) == 1, "ningún check pasó, o sea que no hizo nada"

    apenas_uno = _Report("INDETERMINATE", [_Signature([
        _Check("signature intact", True),
        _Check("certificate chain to trusted root", False)])])
    assert _run(monkeypatch, apenas_uno) == 1, "uno solo no es el trabajo que hace un PDF"

    # This one is why the count of signatures is checked at all. Every other rule here is
    # satisfied: one failure in total, a name on each certificate, the expected verdict. Only
    # "the fixture carries one signature" is not, and without that rule this passes.
    dos_pero_una_limpia = _Report("INDETERMINATE", [
        _Signature(_real_work()),
        _Signature([_Check("signature intact", True)]),
    ])
    assert _run(monkeypatch, dos_pero_una_limpia) == 1, "dos firmas donde la fixture tiene una"


def test_the_verify_selftest_still_means_valid_when_valid_is_asked_for(monkeypatch):
    """The default, for anybody pointing this at a genuinely signed document. A valid signature
    has nothing failing, so the count this holds has to follow the verdict rather than sit at the
    one the fixture happens to produce."""
    intacta = _Report("VALID", [_Signature([_Check("signature intact", True)])])
    assert _run(monkeypatch, intacta, expected="VALID") == 0

    # One passing check is enough here and three are demanded of the fixture, because the number
    # belongs to a format rather than to signatures: a detached CMS yields three and a XAdES up to
    # ten. Somebody pointing this at a document of their own chose the format, and CI did not.
    vacia = _Report("VALID", [_Signature([])])
    assert _run(monkeypatch, vacia, expected="VALID") == 1

    con_fallo = _Report("VALID", [_Signature([_Check("signature intact", True),
                                              _Check("chain", False)])])
    assert _run(monkeypatch, con_fallo, expected="VALID") == 1


def test_the_verify_selftest_rejects_the_wrong_verdict(monkeypatch):
    assert _run(monkeypatch, _fixture_shaped(), expected="VALID") == 1

    # Everything structural agrees here and only the verdict differs, which is the case the other
    # rules cannot see. A build that read the file and called it INVALID would otherwise pass.
    invalida = _Report("INVALID", [_Signature(_real_work())])
    assert _run(monkeypatch, invalida, expected="INDETERMINATE") == 1
