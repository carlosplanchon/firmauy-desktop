# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Rebuild the platform icon containers from ``assets/icon.svg``.

    uv run python -m tools.make_icons            # write icon.ico and icon.icns
    uv run python -m tools.make_icons --check    # say what would change, write nothing

The SVG is the source. Every size in a .ico or an .icns is rendered from the vector rather than
resampled from one 512 pixel PNG, which is the whole reason the SVG exists: a 16 pixel icon
downscaled from 512 loses the chip's gutters entirely.

``icon.png`` is deliberately not regenerated. It is the original artwork, it is what the Linux
desktop entry points at, and this file reproduces it rather than the other way round.

Lives in ``tools/`` for the same reason as everything else here: ``packages.find`` looks under
``src/``, so this cannot end up inside a wheel.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, QSize          # noqa: E402
from PySide6.QtGui import QIcon, QImage                       # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "src" / "firmauy_desktop" / "assets"
SVG = ASSETS / "icon.svg"

# What Windows asks for, which is the set the existing .ico already carried.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# macOS icon types that take a PNG payload, and the pixel size each one means. The @2x entries are
# the same pixels under a different name: macOS picks by name, not by inspecting the image.
ICNS_TYPES = (
    (b"icp4", 16), (b"icp5", 32), (b"ic11", 32), (b"ic12", 64),
    (b"ic07", 128), (b"ic13", 256), (b"ic08", 256), (b"ic14", 512),
    (b"ic09", 512), (b"ic10", 1024),
)


def render(size: int) -> QImage:
    """The SVG at one size, drawn at that size rather than scaled down from another."""
    image = QIcon(str(SVG)).pixmap(QSize(size, size)).toImage()
    if image.isNull() or image.width() != size:
        raise SystemExit(f"the SVG did not render at {size}px: is the Qt svg icon plugin there?")
    return image


def png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def build_ico() -> bytes:
    """A .ico is a small directory followed by the images, here all stored as PNG.

    PNG-in-ICO has been read by Windows since Vista and keeps the file a tenth of the size of the
    same set as bitmaps.
    """
    images = [png_bytes(render(size)) for size in ICO_SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))         # reserved, type 1 = icon, count
    offset = len(header) + 16 * len(images)
    entries, payload = b"", b""
    for size, data in zip(ICO_SIZES, images):
        # 0 means 256 in this field, which is why the format tops out there.
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32,
                               len(data), offset)
        offset += len(data)
        payload += data
    return header + entries + payload


def build_icns() -> bytes:
    """An .icns is a length-prefixed container of length-prefixed typed chunks, nothing more."""
    chunks = b""
    for kind, size in ICNS_TYPES:
        data = png_bytes(render(size))
        chunks += kind + struct.pack(">I", len(data) + 8) + data
    return b"icns" + struct.pack(">I", len(chunks) + 8) + chunks


# --- reading the containers back ---------------------------------------------

def ico_payloads(data: bytes) -> dict:
    """The images inside a .ico, keyed by pixel size. The inverse of ``build_ico``."""
    count = struct.unpack("<H", data[4:6])[0]
    out = {}
    for i in range(count):
        entry = data[6 + i * 16:6 + (i + 1) * 16]
        length, offset = struct.unpack("<II", entry[8:16])
        out[entry[0] or 256] = data[offset:offset + length]
    return out


def icns_payloads(data: bytes) -> dict:
    """The chunks inside an .icns, keyed by type. The inverse of ``build_icns``."""
    out = {}
    pos, end = 8, struct.unpack(">I", data[4:8])[0]
    while pos < end:
        kind = data[pos:pos + 4]
        length = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        out[kind] = data[pos + 8:pos + length]
        pos += length
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report what would change and write nothing")
    args = parser.parse_args()

    QApplication(sys.argv)
    if not SVG.is_file():
        raise SystemExit(f"no está {SVG}")

    # Byte equality here, unlike the test that guards these files, which compares the decoded
    # pixels instead. The two are asking different questions. This one is "is there anything at all
    # to write", where rewriting an identical-looking file costs nothing; the test is "does the
    # committed binary still show what the SVG says", and answering that in bytes makes it a test
    # of which Qt happened to encode the PNGs.
    changed = False
    for name, build in (("icon.ico", build_ico), ("icon.icns", build_icns)):
        target = ASSETS / name
        data = build()
        same = target.is_file() and target.read_bytes() == data
        if same:
            print(f"  {name}: sin cambios ({len(data):,} bytes)")
            continue
        changed = True
        if args.check:
            print(f"  {name}: cambiaría ({len(data):,} bytes)")
            continue
        target.write_bytes(data)
        print(f"  {name}: escrito ({len(data):,} bytes)")

    # Qt reads both containers back, so this is a real check rather than a hopeful one.
    for name in ("icon.ico", "icon.icns"):
        path = ASSETS / name
        if path.is_file() and QImage(str(path)).isNull():
            raise SystemExit(f"{name} quedó ilegible")
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
