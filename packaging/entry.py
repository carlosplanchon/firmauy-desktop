# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""PyInstaller entry point for FirmaUY Desktop.

A thin launcher that lives outside the package, so PyInstaller analyses it as the top-level
script and imports ``firmauy_desktop`` as a normal package (avoids the in-package __main__
double-import pitfall).
"""

from firmauy_desktop.app import main

if __name__ == "__main__":
    raise SystemExit(main())
