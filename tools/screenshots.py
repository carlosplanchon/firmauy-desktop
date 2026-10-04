# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""The README's screenshots, rebuilt from synthetic data.

    uv run python -m tools.screenshots               # write docs/screenshots/
    uv run python -m tools.screenshots --scheme dark

The whole window, not a bare view: the sidebar is half of what the app looks like now, and the
storybook deliberately renders screens on their own.

Every value in these comes from ``tools/samples.py``. The card is never touched, and no image of
a person ever reaches the repository: the cardholder photo is a flat rectangle generated at run
time. CONTRIBUTING forbids real names, numbers and photos in screenshots, and the only way to
keep that true over time is for the screenshots to be built rather than captured.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication                    # noqa: E402

from tools import cardguard                                   # noqa: E402

cardguard.block_card_calls()                                  # before any view is built

from firmauy_desktop.views import doctor_view                 # noqa: E402
from tools import samples                                     # noqa: E402

# Diagnóstico asks pcscd for the reader list once its checks come back, so driving the first
# handler starts the second call for real. The guard caught exactly that on the first run of
# this file, which is the point of having it.
doctor_view.list_readers = lambda *a, **k: samples.readers()

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
# Tall enough for Verificar's whole answer: the verdict, the revocation claim under it (two
# lines since it stopped being one centred caption), the pointer to firma.gub.uy, the file,
# the signer, the four open checks and the disclaimer strip. At 660 the last checks came out
# clipped mid-line, which in a README reads as a broken render rather than as a scrollbar,
# and at 700 the two rows the window grew since (the strip and the pointer) put them right
# back.
SIZE = (900, 780)


def _shots(window):
    """Name, and what to do to the window to get there. Ordered as the README reads."""
    from firmauy_desktop.views import identity_view, verify_view

    def sign(_w):
        pass

    def verify(w):
        # What load() would have done. Driving the handler straight skips it, and a shot of a
        # verdict over a generic drop prompt is a state the app refuses to show.
        w._verify._drop.show_files(["/home/ana/contrato.pdf.p7s"])
        verify_view.VerifyView._on_done(w._verify, samples.verify_valid())
        w._verify._details_box.set_expanded(True)

    def identity(w):
        identity_view.IdentityView._on_done(w._identity, samples.identity_read(photo=True))

    def doctor(w):
        doctor_view.DoctorView._on_checked(w._doctor, samples.doctor_broken())

    return (("firmar", "sign", sign), ("verificar", "verify", verify),
            ("mi-cedula", "identity", identity), ("diagnostico", "doctor", doctor))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scheme", default="light", choices=("light", "dark", "both"))
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    from firmauy_desktop import settings
    settings.apply_identity(app)
    # A store of its own, so the images do not depend on who runs this and closing a window per
    # image saves nothing over anybody's geometry. Avanzado is listed, as the README has always
    # shown it: off by default, but a screen the text describes should not be missing from the
    # picture of the app.
    from tools import sandbox
    sandbox.isolate_settings(settings.Settings(advanced_mode=True))
    from firmauy_desktop.main_window import MainWindow
    from firmauy_desktop.ui.theming import theme

    schemes = ("light", "dark") if args.scheme == "both" else (args.scheme,)
    written = 0
    for scheme in schemes:
        theme.apply(app, scheme)
        folder = args.out / scheme if len(schemes) > 1 else args.out
        folder.mkdir(parents=True, exist_ok=True)
        for name, key, build in _shots(None):
            window = MainWindow()
            window.resize(*SIZE)
            window.show()
            app.processEvents()
            window.go_to(key)
            build(window)
            app.processEvents()
            window.grab().save(str(folder / f"{name}.png"))
            window.close()
            written += 1
    print(f"{written} capturas en {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
