# PyInstaller build spec for FirmaUY Desktop.
#
# Build (onedir):  uv run pyinstaller --clean --noconfirm packaging/firmauy-desktop.spec
# Output:          dist/firmauy-desktop/  (run dist/firmauy-desktop/firmauy-desktop)
#
# The app only uses QtCore, QtGui and QtWidgets, so we let PyInstaller's PySide6 hook pull just
# their dependency closure instead of `--collect-all PySide6`, which dragged in QtWebEngine (a full
# Chromium, ~200 MB on its own), QML/Quick and multimedia and pushed the bundle past 800 MB. The
# excludes below are the safety net that keeps those heavy, unused Qt modules out.

import os

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

entry = os.path.join(SPECPATH, "entry.py")
src = os.path.normpath(os.path.join(SPECPATH, "..", "src"))

datas = []
binaries = []
hiddenimports = []

# firmauy ships package data (the bundled national CA certificates) that must travel with the app,
# and its submodules are imported lazily from firmauy.api. pyhanko and its cert validator carry data
# and plugins used for PDF/CMS signing and verification.
for pkg in ("firmauy", "pyhanko", "pyhanko_certvalidator"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# pyscard loads its PC/SC backend submodules dynamically.
hiddenimports += collect_submodules("smartcard")

# The app's own package data (the window icon), which PyInstaller does not pick up on its own.
datas += collect_data_files("firmauy_desktop")

# Qt modules the app never imports. Excluding them keeps QtWebEngine, QML/Quick, 3D, charts,
# multimedia, sensors and the like out of the bundle.
excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtWebView",
    "PySide6.QtQml", "PySide6.QtQmlModels", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras", "PySide6.Qt3DLogic",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtTest", "PySide6.QtHelp",
    "PySide6.QtSql", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech",
    # Non-Qt heavyweights sometimes pulled transitively but unused here.
    "tkinter",
]

a = Analysis(
    [entry],
    pathex=[src],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="firmauy-desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app: no console window on Windows/macOS
    # Windows reads the executable's icon from here (the .ico carries every size it asks for).
    # Ignored on Linux, where the desktop entry points at the PNG instead.
    icon=os.path.join(src, "firmauy_desktop", "assets", "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="firmauy-desktop",
)

# macOS only: PyInstaller ignores this everywhere else, so it costs nothing on Linux or Windows.
# The .icns is the one thing Finder and the Dock read, and neither will look at the .ico or the
# PNG. Both containers are rebuilt from assets/icon.svg by tools/make_icons.py.
#
# NOT VERIFIED ON MACOS: there is no Mac in this project's CI yet. Confirm the identifier before
# anything is signed or notarised with it, because it is what the signature binds to.
app = BUNDLE(
    coll,
    name="FirmaUY Desktop.app",
    icon=os.path.join(src, "firmauy_desktop", "assets", "icon.icns"),
    # The same string settings.APP_ID carries, which is also the base name of the Linux desktop
    # entry. One identity across the three platforms, held there by a test: an application known
    # by two names is two applications to anything that catalogues it.
    bundle_identifier="com.firmauy.firmauydesktop",
    info_plist={
        "CFBundleDisplayName": "FirmaUY Desktop",
        "CFBundleShortVersionString": "0.1.0",
        # Retina: without it macOS runs the app through the 2x upscaler and every label is soft.
        "NSHighResolutionCapable": True,
        # The app talks to a card reader over PC/SC, never to a camera, a microphone or a disk it
        # was not handed, so there is no other entitlement to declare here.
        "LSMinimumSystemVersion": "11.0",
    },
)
